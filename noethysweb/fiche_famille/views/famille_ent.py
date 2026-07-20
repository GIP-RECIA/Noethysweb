from datetime import date
from concurrent.futures import ThreadPoolExecutor
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db import transaction
from urllib.parse import urlencode

from core.views.base import CustomView
from core.models import (
    Individu, Famille, Rattachement, Prestation, Inscription, Deduction,
    Note, Piece, Historique, Destinataire, DestinataireSMS, QuestionnaireReponse,
    PortailRenseignement, ContactUrgence, Assurance, SondageRepondant, Cotisation, Mandat,
    Ecole, Classe, Scolarite,
)
from core.utils.utils_ent import search_by_name, search_users, get_user, get_headers
from django.shortcuts import get_object_or_404

MAX_WORKERS = 5  # limite le nombre d'appels simultanés vers l'ENT


def _get_users_parallel(ent_ids):
    """ Récupère plusieurs utilisateurs ENT en parallèle. Retourne {ent_id: data ou None}. """
    ent_ids = list(dict.fromkeys(ent_ids))  # dédoublonne en gardant l'ordre
    if not ent_ids:
        return {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        resultats = executor.map(lambda ent_id: (ent_id, get_user(ent_id)), ent_ids)
    return dict(resultats)

# pour formater les dates de naissnace 
def _parse_date(valeur):
    if not valeur:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _convertir_civilite(valeur):
    """Convertit la civilité ENT (texte) en ID Noethysweb (catégorie adulte : Monsieur/Mademoiselle/Madame)."""
    mapping = {
        "M.": 1, "M": 1, "Mr": 1, "Monsieur": 1,
        "Mme": 3, "Madame": 3,
        "Melle": 2, "Mlle": 2, "Mademoiselle": 2,
    }
    return mapping.get(valeur, 1)


def _civilite_enfant_defaut():
    """
    Civilité par défaut pour un élève importé (catégorie enfant : Garçon/Fille). L'ENT ne
    fournit jamais le sexe de l'élève (champ "title" toujours vide, vérifié sur plusieurs
    élèves réels) - valeur arbitraire, toujours combinée à civilite_a_verifier=True pour
    qu'un agent la confirme.
    """
    return 4  # Garçon


def _adresses_differentes(parent1_data, parent2_data):
    def normaliser(data):
        rue = (data.get("address") or "").strip().lower()
        cp = (data.get("zipCode") or "").strip().lower()
        return f"{rue}|{cp}"
    adr1 = normaliser(parent1_data)
    adr2 = normaliser(parent2_data)
    if not adr1.replace("|", "").strip() or not adr2.replace("|", "").strip():
        return False
    return adr1 != adr2


def _normaliser_enfant(data):
    """Ajoute ecole_nom, ecole_uai, ecole_ent_id et classe_nom selon le format retourné (admin/list ou get_user)."""
    # Ecole : admin/list -> structures[0].name/uai/id | get_user -> structureNodes[0].name/UAI/id
    # L'identifiant ENT (id) est capturé en plus du nom/UAI car il est toujours présent, alors
    # que l'UAI est parfois absent selon les établissements (observé en pratique) - utile pour
    # reconnaître une école de façon fiable même sans UAI.
    structures = data.get("structures") or []
    struct_nodes = data.get("structureNodes") or []
    if structures and isinstance(structures[0], dict):
        data["ecole_nom"] = structures[0].get("name")
        data["ecole_uai"] = structures[0].get("uai")
        data["ecole_ent_id"] = structures[0].get("id")
    elif struct_nodes and isinstance(struct_nodes[0], dict):
        data["ecole_nom"] = struct_nodes[0].get("name")
        data["ecole_uai"] = struct_nodes[0].get("UAI")
        data["ecole_ent_id"] = struct_nodes[0].get("id")
    else:
        data["ecole_nom"] = None
        data["ecole_uai"] = None
        data["ecole_ent_id"] = None

    # Classe : admin/list -> allClasses[0].name | get_user -> classes[0] = "id$NomClasse"
    all_classes = data.get("allClasses") or []
    classes_raw = data.get("classes") or []
    if all_classes and isinstance(all_classes[0], dict):
        data["classe_nom"] = all_classes[0].get("name")
    elif classes_raw and isinstance(classes_raw[0], str) and "$" in classes_raw[0]:
        data["classe_nom"] = classes_raw[0].split("$")[-1]
    else:
        data["classe_nom"] = None
    return data


def _get_ou_creer_ecole(ecole_nom, uai, ent_id=None):
    """
    Retrouve l'École Noethys correspondant à cette école ENT (par identifiant ENT en priorité -
    toujours présent -, puis par UAI, puis par nom exact), ou la crée si elle n'existe vraiment
    pas encore.

    Le repli par nom est nécessaire car l'ENT ne fournit pas toujours un UAI par élève (observé
    en pratique) - sans lui, une école déjà créée serait sinon dupliquée à chaque import. Mesure
    intermédiaire en attendant l'import dédié des écoles par UAI (bug remonté à Édifice).
    """
    if not ecole_nom:
        return None
    if ent_id:
        ecole = Ecole.objects.filter(ent_id=ent_id).first()
        if ecole:
            return ecole
    if uai:
        ecole = Ecole.objects.filter(uai=uai).first()
        if ecole:
            return ecole
    ecole = Ecole.objects.filter(nom=ecole_nom).first()
    if ecole:
        # Complète l'école déjà connue avec l'identifiant ENT si elle ne l'avait pas encore,
        # pour fiabiliser les prochaines correspondances.
        if ent_id and not ecole.ent_id:
            ecole.ent_id = ent_id
            ecole.save()
        return ecole
    return Ecole.objects.create(nom=ecole_nom, uai=uai or None, ent_id=ent_id or None)


def _get_annee_scolaire_par_defaut():
    """
    Retourne (date_debut, date_fin) de l'année scolaire en cours (1er septembre -> 31 août),
    à utiliser quand l'ENT ne fournit pas de dates de scolarité (observé systématiquement
    dans les données de recette : startDateClasses/endDateClasses toujours vides).
    """
    aujourdhui = date.today()
    annee_debut = aujourdhui.year if aujourdhui.month >= 8 else aujourdhui.year - 1
    return date(annee_debut, 9, 1), date(annee_debut + 1, 8, 31)


def _get_ou_creer_classe(ecole, classe_nom, date_debut_ent, date_fin_ent):
    """
    Retrouve la Classe Noethys correspondante dans cette école (par nom), ou la crée si elle
    n'existe pas encore. Utilise les dates fournies par l'ENT si elles existent, sinon une
    année scolaire par défaut.
    """
    if not ecole or not classe_nom:
        return None
    classe = Classe.objects.filter(ecole=ecole, nom=classe_nom).first()
    if classe:
        return classe
    date_debut_defaut, date_fin_defaut = _get_annee_scolaire_par_defaut()
    return Classe.objects.create(
        ecole=ecole,
        nom=classe_nom,
        date_debut=_parse_date(date_debut_ent) or date_debut_defaut,
        date_fin=_parse_date(date_fin_ent) or date_fin_defaut,
    )


def _creer_scolarite(individu, eleve_data):
    """
    Crée la ligne Scolarité (école + classe) d'un individu à partir des données ENT de
    l'élève. `eleve_data` doit avoir été passé par `_normaliser_enfant()` au préalable.
    Ne fait rien si l'ENT ne donne aucune école pour cet élève.
    """
    ecole_nom = eleve_data.get("ecole_nom")
    if not ecole_nom:
        return None

    ecole = _get_ou_creer_ecole(ecole_nom, eleve_data.get("ecole_uai"), eleve_data.get("ecole_ent_id"))
    classe = _get_ou_creer_classe(
        ecole, eleve_data.get("classe_nom"),
        eleve_data.get("startDateClasses"), eleve_data.get("endDateClasses"),
    )

    date_debut_defaut, date_fin_defaut = _get_annee_scolaire_par_defaut()
    return Scolarite.objects.create(
        individu=individu,
        ecole=ecole,
        classe=classe,
        date_debut=_parse_date(eleve_data.get("startDateClasses")) or date_debut_defaut,
        date_fin=_parse_date(eleve_data.get("endDateClasses")) or date_fin_defaut,
    )


def _importer_eleve_ent(eleve_ent_id, eleve_data=None, parents_cache=None):
    """
    Importe un élève et sa famille depuis l'ENT (logique partagée entre l'import unitaire
    et l'import en masse). `eleve_data` et `parents_cache` peuvent être fournis pré-chargés
    (récupérés en parallèle en amont) pour éviter de refaire les appels API un par un.
    Retourne un dict {"statut": "importe"|"deja_importe"|"erreur", "message": str, "famille_id": int|None,
    "type": "famille_existante"|"nouvelle_famille"|"nouvelle_famille_separee"|None}. Le champ "type" précise,
    quand statut="importe", si l'élève a rejoint une famille déjà créée (frère/soeur) ou si une nouvelle
    famille a été créée pour lui — utile pour ne pas confondre "élèves importés" et "familles créées"
    dans un résumé d'import en masse.
    """
    if Individu.objects.filter(ent_id=eleve_ent_id).exists():
        return {"statut": "deja_importe", "message": "Élève déjà importé.", "famille_id": None, "type": None}

    if eleve_data is None:
        eleve_data = get_user(eleve_ent_id)
    if not eleve_data:
        return {"statut": "erreur", "message": "Impossible de récupérer les données depuis l'ENT.", "famille_id": None, "type": None}

    def Get_parent_data(parent_id):
        if parents_cache is not None and parent_id in parents_cache:
            return parents_cache[parent_id]
        return get_user(parent_id)

    try:
        with transaction.atomic():
            eleve = Individu(
                nom=eleve_data.get("lastName", ""),
                prenom=eleve_data.get("firstName", ""),
                civilite=_civilite_enfant_defaut(),
                civilite_a_verifier=True,
                date_naiss=_parse_date(eleve_data.get("birthDate")),
                mail=eleve_data.get("email") or None,
                tel_domicile=eleve_data.get("phone") or None,
                tel_mobile=eleve_data.get("mobile") or None,
                rue_resid=eleve_data.get("address") or None,
                cp_resid=eleve_data.get("zipCode") or None,
                ville_resid=eleve_data.get("city") or None,
                ent_id=eleve_ent_id,
            )
            eleve.save()

            # Enregistre la scolarité (école/classe) de l'élève, indépendamment de la
            # situation familiale déterminée plus bas.
            eleve_data = _normaliser_enfant(eleve_data)
            _creer_scolarite(eleve, eleve_data)

            parents_data = []
            for parent_info in eleve_data.get("parents", []):
                parent_data = Get_parent_data(parent_info["id"])
                if parent_data:
                    parents_data.append((parent_info["id"], parent_data))

            parents_existants = []
            for ent_id_parent, parent_data in parents_data:
                parent = Individu.objects.filter(ent_id=ent_id_parent).first()
                if parent:
                    parents_existants.append(parent)

            if parents_existants:
                # Au moins un parent existe déjà — ajouter l'enfant à ses familles
                familles_ajoutees = set()
                for parent in parents_existants:
                    for ratt in Rattachement.objects.filter(individu=parent, categorie=1):
                        if ratt.famille_id not in familles_ajoutees:
                            Rattachement.objects.create(individu=eleve, famille=ratt.famille, categorie=2, titulaire=False)
                            ratt.famille.Maj_infos()
                            familles_ajoutees.add(ratt.famille_id)
                famille_id = list(familles_ajoutees)[0]
                return {"statut": "importe", "message": f"{eleve.prenom} {eleve.nom} ajouté(e) à une famille existante.", "famille_id": famille_id, "type": "famille_existante"}

            # Détecter si les parents ont des adresses différentes
            separes = (
                len(parents_data) >= 2 and
                _adresses_differentes(parents_data[0][1], parents_data[1][1])
            )

            if separes:
                # Créer une famille séparée par parent
                premiere_famille_id = None
                for ent_id_parent, parent_data in parents_data:
                    famille = Famille()
                    famille.mode_separation = "automatique"
                    famille.save()
                    if premiere_famille_id is None:
                        premiere_famille_id = famille.pk
                    parent = Individu(
                        nom=parent_data.get("lastName", ""),
                        prenom=parent_data.get("firstName", ""),
                        civilite=_convertir_civilite(parent_data.get("title")),
                        civilite_a_verifier=True,
                        date_naiss=_parse_date(parent_data.get("birthDate")),
                        mail=parent_data.get("email") or None,
                        tel_domicile=parent_data.get("phone") or None,
                        tel_mobile=parent_data.get("mobile") or None,
                        rue_resid=parent_data.get("address") or None,
                        cp_resid=parent_data.get("zipCode") or None,
                        ville_resid=parent_data.get("city") or None,
                        ent_id=ent_id_parent,
                    )
                    parent.save()
                    Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
                    Rattachement.objects.create(individu=eleve, famille=famille, categorie=2, titulaire=False)
                    famille.Maj_infos()
                return {"statut": "importe", "message": f"{eleve.prenom} {eleve.nom} importé(e), 2 familles séparées créées.", "famille_id": premiere_famille_id, "type": "nouvelle_famille_separee"}

            else:
                # Famille unique
                famille = Famille()
                famille.save()
                Rattachement.objects.create(individu=eleve, famille=famille, categorie=2, titulaire=False)
                for ent_id_parent, parent_data in parents_data:
                    parent = Individu(
                        nom=parent_data.get("lastName", ""),
                        prenom=parent_data.get("firstName", ""),
                        civilite=_convertir_civilite(parent_data.get("title")),
                        civilite_a_verifier=True,
                        date_naiss=_parse_date(parent_data.get("birthDate")),
                        mail=parent_data.get("email") or None,
                        tel_domicile=parent_data.get("phone") or None,
                        tel_mobile=parent_data.get("mobile") or None,
                        rue_resid=parent_data.get("address") or None,
                        cp_resid=parent_data.get("zipCode") or None,
                        ville_resid=parent_data.get("city") or None,
                        ent_id=ent_id_parent,
                    )
                    parent.save()
                    Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
                famille.Maj_infos()
                return {"statut": "importe", "message": f"{eleve.prenom} {eleve.nom} importé(e).", "famille_id": famille.pk, "type": "nouvelle_famille"}
    except Exception as e:
        return {"statut": "erreur", "message": str(e), "famille_id": None, "type": None}


class ImporterFamilleEnt(CustomView, TemplateView):
    template_name = "fiche_famille/famille_ent_import.html"
    menu_code = "famille_liste"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Importer une famille depuis l'ENT"
        context["box_titre"] = "Recherche dans l'ENT"
        context["box_introduction"] = "Saisissez le prénom et le nom d'un enfant ou d'un parent pour rechercher la famille dans l'ENT."
        context["resultats"] = kwargs.get("resultats", None)
        context["last_name"] = kwargs.get("last_name", "")
        context["first_name"] = kwargs.get("first_name", "")
        context["erreur"] = kwargs.get("erreur", None)
        return context

    def get(self, request, *args, **kwargs):
        # Lire les résultats depuis la session puis les effacer
        resultats = request.session.pop("ent_resultats", None)
        last_name = request.session.pop("ent_last_name", "")
        first_name = request.session.pop("ent_first_name", "")
        erreur = request.session.pop("ent_erreur", None)

        return self.render_to_response(self.get_context_data(
            resultats=resultats,
            last_name=last_name,
            first_name=first_name,
            erreur=erreur,
        ))

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "rechercher")

        if action == "rechercher":
            last_name = request.POST.get("last_name", "").strip()
            first_name = request.POST.get("first_name", "").strip()
            if not last_name or not first_name:
                request.session["ent_erreur"] = "Veuillez saisir le prénom ET le nom."
                request.session["ent_last_name"] = last_name
                request.session["ent_first_name"] = first_name
                return HttpResponseRedirect(reverse("ent_import_famille"))
            self._effectuer_recherche(request, last_name, first_name)
            return HttpResponseRedirect(reverse("ent_import_famille"))

        elif action == "importer":
            return self._importer(request)

        return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

    def _effectuer_recherche(self, request, last_name, first_name):
        request.session["ent_last_name"] = last_name
        request.session["ent_first_name"] = first_name

        # Vérifie la connexion avant la recherche : search_by_name() renvoie une liste vide
        # aussi bien quand la recherche ne trouve rien que quand la connexion échoue
        # (identifiants incorrects, ENT désactivé...) - sans ce test, l'agent verrait
        # "Aucun résultat" dans les deux cas sans savoir qu'il y a un vrai problème.
        if get_headers() is None:
            request.session["ent_erreur"] = "Impossible de se connecter à l'ENT. Vérifiez que la connexion est active et que les identifiants sont corrects, ou réessayez dans quelques instants (le service ENT peut être temporairement indisponible)."
            return

        resultats_bruts = search_by_name(last_name=last_name, first_name=first_name)

        if resultats_bruts is None:
            request.session["ent_erreur"] = "La connexion à l'ENT a échoué. Vérifiez le paramétrage ENT."
            return

        if len(resultats_bruts) == 0:
            request.session["ent_erreur"] = f"Aucun résultat pour « {first_name} {last_name} » dans l'ENT."
            return

        # Construire une liste de familles centrées sur l'enfant, sans doublons
        familles = {}  # clé = ent_id de l'enfant

        # Phase 1 : récupère en parallèle le détail de chaque résultat de recherche
        ids_a_recuperer = [user["id"] for user in resultats_bruts if user.get("id")]
        donnees_users = _get_users_parallel(ids_a_recuperer)

        ids_enfants_a_recuperer = []
        for user in resultats_bruts:
            # L'endpoint /admin/list retourne le profil dans "type", pas "profiles"
            user_type = user.get("type") or ""
            user_data = donnees_users.get(user.get("id"))
            if not user_data:
                continue

            if "Student" in user_type:
                # Résultat direct : c'est un élève
                familles[user_data["id"]] = _normaliser_enfant(user_data)

            elif "Relative" in user_type:
                # C'est un parent : on mémorise ses enfants pour la phase 2
                for child in user_data.get("children", []):
                    if child.get("id") and child["id"] not in familles:
                        ids_enfants_a_recuperer.append(child["id"])

        # Phase 2 : récupère en parallèle les enfants des parents trouvés
        if ids_enfants_a_recuperer:
            donnees_enfants = _get_users_parallel(ids_enfants_a_recuperer)
            for enfant_data in donnees_enfants.values():
                if enfant_data and enfant_data["id"] not in familles:
                    familles[enfant_data["id"]] = _normaliser_enfant(enfant_data)

        if not familles:
            request.session["ent_erreur"] = f"Aucune famille trouvée pour « {first_name} {last_name} » dans l'ENT."
            return

        # Phase 3 : récupère en parallèle le détail de tous les parents de tous les enfants trouvés
        ids_parents_a_recuperer = []
        for enfant in familles.values():
            for parent in enfant.get("parents", []):
                if parent.get("id"):
                    ids_parents_a_recuperer.append(parent["id"])
        donnees_parents = _get_users_parallel(ids_parents_a_recuperer)

        resultats = []
        for enfant in familles.values():
            # Vérifier si déjà importé
            individu_existant = Individu.objects.filter(ent_id=enfant["id"]).first()
            if individu_existant:
                ratt = Rattachement.objects.filter(individu=individu_existant, categorie=2).first()
                enfant["deja_importe"] = True
                enfant["famille_id"] = ratt.famille_id if ratt else None
            else:
                enfant["deja_importe"] = False
                enfant["famille_id"] = None

            # Récupérer les détails des parents (déjà récupérés en parallèle à la phase 3)
            parents_details = []
            for parent in enfant.get("parents", []):
                if not parent.get("id"):
                    continue
                parent_data = donnees_parents.get(parent["id"])
                if parent_data:
                    parents_details.append(parent_data)
            enfant["parents_details"] = parents_details

            if len(parents_details) >= 2:
                enfant["adresses_differentes"] = _adresses_differentes(parents_details[0], parents_details[1])
            else:
                enfant["adresses_differentes"] = False

            # Vérifier si les parents existent déjà dans Noethysweb
            enfant["parents_existants"] = False
            enfant["parents_existants_msg"] = None
            if not enfant["deja_importe"]:
                parents_en_base = []
                for parent in enfant.get("parents", []):
                    if parent.get("id"):
                        p = Individu.objects.filter(ent_id=parent["id"]).first()
                        if p:
                            parents_en_base.append(p)
                if parents_en_base:
                    enfant["parents_existants"] = True
                    noms = " et ".join([f"{p.prenom} {p.nom}" for p in parents_en_base])
                    familles_parents = Rattachement.objects.filter(
                        individu__in=parents_en_base, categorie=1
                    ).select_related("famille").values_list("famille__nom", flat=True).distinct()
                    noms_familles = ", ".join(familles_parents)
                    if len(familles_parents) > 1:
                        enfant["parents_existants_msg"] = f"Les parents {noms} existent déjà (familles séparées). {enfant.get('firstName', '')} sera ajouté aux familles {noms_familles}."
                    else:
                        enfant["parents_existants_msg"] = f"Les parents {noms} existent déjà. {enfant.get('firstName', '')} sera ajouté à la famille {noms_familles}."

            resultats.append(enfant)

        request.session["ent_resultats"] = resultats

    def _importer(self, request):
        eleve_ent_id = request.POST.get("eleve_ent_id")
        if not eleve_ent_id:
            messages.error(request, "Données manquantes.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        resultat = _importer_eleve_ent(eleve_ent_id)

        if resultat["statut"] == "deja_importe":
            messages.warning(request, "Cet élève a déjà été importé.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))
        elif resultat["statut"] == "erreur":
            messages.error(request, resultat["message"])
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))
        else:
            messages.success(request, resultat["message"])
            return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": resultat["famille_id"]}))


class ImporterEnMasseEnt(CustomView, TemplateView):
    template_name = "fiche_famille/famille_ent_import_masse.html"
    menu_code = "famille_liste"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Importer en masse depuis l'ENT"
        context["box_titre"] = "Import en masse"
        context["box_introduction"] = "Sélectionnez les élèves à importer depuis l'ENT, puis cliquez sur Importer."

        # Vérifie la connexion avant d'interroger l'ENT : search_users() renvoie [] aussi bien
        # quand l'ENT n'a réellement aucun élève que quand la connexion échoue (identifiants
        # incorrects, ENT désactivé, panne...). Sans cette vérification, l'agent verrait le même
        # message "Aucun élève trouvé" dans les deux cas, sans savoir qu'il y a un vrai problème.
        context["erreur_connexion"] = get_headers() is None

        eleves = []
        if not context["erreur_connexion"]:
            eleves_bruts = search_users(profile="Student")
            for eleve_data in eleves_bruts:
                eleve_data = _normaliser_enfant(dict(eleve_data))
                individu_existant = Individu.objects.filter(ent_id=eleve_data.get("id")).first()
                eleve_data["deja_importe"] = individu_existant is not None
                if individu_existant:
                    ratt = Rattachement.objects.filter(individu=individu_existant, categorie=2).first()
                    eleve_data["famille_id"] = ratt.famille_id if ratt else None
                else:
                    eleve_data["famille_id"] = None
                eleves.append(eleve_data)

        context["eleves"] = eleves
        context["nb_a_importer"] = sum(1 for e in eleves if not e["deja_importe"])
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        context["resume"] = request.session.pop("ent_import_masse_resume", None)
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        ids_selectionnes = request.POST.getlist("eleves_ent_id")
        if not ids_selectionnes:
            messages.error(request, "Aucun élève sélectionné.")
            return HttpResponseRedirect(reverse("ent_import_masse"))

        # Phase 1 : récupère en parallèle le détail de chaque élève sélectionné
        eleves_data = _get_users_parallel(ids_selectionnes)

        # Phase 2 : récupère en parallèle le détail de tous les parents concernés
        ids_parents = []
        for eleve_data in eleves_data.values():
            if eleve_data:
                for parent_info in eleve_data.get("parents", []):
                    if parent_info.get("id"):
                        ids_parents.append(parent_info["id"])
        parents_cache = _get_users_parallel(ids_parents)

        nb_eleves_importes, nb_ignores, nb_erreurs = 0, 0, 0
        nb_nouvelles_familles, nb_familles_existantes = 0, 0
        erreurs_detail = []
        for eleve_ent_id in ids_selectionnes:
            resultat = _importer_eleve_ent(eleve_ent_id, eleve_data=eleves_data.get(eleve_ent_id), parents_cache=parents_cache)
            if resultat["statut"] == "importe":
                nb_eleves_importes += 1
                if resultat["type"] == "famille_existante":
                    nb_familles_existantes += 1
                elif resultat["type"] == "nouvelle_famille_separee":
                    nb_nouvelles_familles += 2  # 2 fiches créées (parents séparés)
                else:
                    nb_nouvelles_familles += 1
            elif resultat["statut"] == "deja_importe":
                nb_ignores += 1
            else:
                nb_erreurs += 1
                erreurs_detail.append(resultat["message"])

        request.session["ent_import_masse_resume"] = {
            "nb_eleves_importes": nb_eleves_importes,
            "nb_nouvelles_familles": nb_nouvelles_familles,
            "nb_familles_existantes": nb_familles_existantes,
            "nb_ignores": nb_ignores,
            "nb_erreurs": nb_erreurs,
            "erreurs_detail": erreurs_detail,
        }
        return HttpResponseRedirect(reverse("ent_import_masse"))


class FusionnerFamilles(CustomView, TemplateView):
    template_name = "fiche_famille/famille_ent_fusionner.html"
    menu_code = "famille_liste"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        idfamille = self.kwargs["idfamille"]
        famille = get_object_or_404(Famille, pk=idfamille)

        # Trouver les familles candidates : celles qui partagent au moins un enfant
        enfants_ids = Rattachement.objects.filter(famille=famille, categorie=2).values_list("individu_id", flat=True)
        familles_candidates = Famille.objects.filter(
            rattachement__individu_id__in=enfants_ids,
            rattachement__categorie=2,
        ).exclude(pk=idfamille).distinct()

        context["page_titre"] = "Fusionner des familles"
        context["box_titre"] = "Fusion de familles"
        context["box_introduction"] = "Sélectionnez la famille avec laquelle fusionner."
        context["famille"] = famille
        context["idfamille"] = idfamille
        context["familles_candidates"] = familles_candidates
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        idfamille = self.kwargs["idfamille"]
        idfamille_source = request.POST.get("idfamille_source")

        if not idfamille_source:
            messages.error(request, "Veuillez sélectionner une famille.")
            return HttpResponseRedirect(reverse("famille_fusionner", kwargs={"idfamille": idfamille}))

        famille_cible = get_object_or_404(Famille, pk=idfamille)
        famille_source = get_object_or_404(Famille, pk=idfamille_source)

        # Déplacer tous les rattachements de la famille source vers la cible (sans doublons)
        for ratt in Rattachement.objects.filter(famille=famille_source):
            deja_present = Rattachement.objects.filter(famille=famille_cible, individu=ratt.individu).exists()
            if not deja_present:
                ratt.famille = famille_cible
                ratt.save()
            else:
                ratt.delete()

        # Migrer toutes les autres données liées à la famille source (factures, prestations,
        # règlements, messages du portail, historique...) vers la famille cible. Sans ça, la
        # suppression ci-dessous plante dès que la famille source a la moindre activité, ou
        # supprime silencieusement certaines données (tables en on_delete=CASCADE).
        # On se base sur Famille._meta.related_objects plutôt qu'une liste figée de modèles,
        # pour que ça reste correct même si un nouveau modèle lié à Famille est ajouté plus tard.
        for related in Famille._meta.related_objects:
            if related.related_model is Rattachement:
                continue  # déjà géré ci-dessus
            champ = related.field.name
            related.related_model.objects.filter(**{champ: famille_source}).update(**{champ: famille_cible})

        # Supprimer la famille source
        famille_source.delete()

        # Réinitialiser le mode_separation
        famille_cible.mode_separation = None
        famille_cible.save()
        famille_cible.Maj_infos()

        messages.success(request, "Les deux familles ont été fusionnées avec succès.")
        return HttpResponseRedirect(reverse("famille_resume", kwargs={"idfamille": idfamille}))


# Tables liées à un individu précis qui doivent suivre la même règle que les Prestations
# lors d'une séparation manuelle (contrairement aux tables liées uniquement à la famille
# dans son ensemble, comme Facture ou Quotient, qui ne migrent jamais).
MODELES_A_MIGRER_PAR_INDIVIDU = [
    Note, Piece, Historique, Destinataire, DestinataireSMS, QuestionnaireReponse,
    PortailRenseignement, ContactUrgence, Assurance, SondageRepondant, Cotisation, Mandat,
]


def _migrer_donnees_individu(model, famille_origine, nouvelle_famille, parent, ids_enfants, titulaire_unique_id):
    """
    Migre vers la nouvelle famille les lignes de `model` qui concernent soit le parent qui
    part, soit un enfant partagé si le parent qui part était l'unique titulaire du dossier.
    Les lignes sans individu renseigné (données générales à la famille) ne migrent jamais.
    """
    nb = model.objects.filter(famille=famille_origine, individu=parent).update(famille=nouvelle_famille)
    if titulaire_unique_id == parent.pk and ids_enfants:
        nb += model.objects.filter(famille=famille_origine, individu_id__in=ids_enfants).update(famille=nouvelle_famille)
    return nb


class SeparerFamille(CustomView, TemplateView):
    template_name = "fiche_famille/famille_ent_separer.html"
    menu_code = "famille_liste"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        idfamille = self.kwargs["idfamille"]
        famille = get_object_or_404(Famille, pk=idfamille)

        representants = Rattachement.objects.filter(famille=famille, categorie=1).select_related("individu")

        context["page_titre"] = "Séparer une famille"
        context["box_titre"] = "Séparation manuelle"
        context["box_introduction"] = "Sélectionnez le parent à déplacer vers une nouvelle famille."
        context["famille"] = famille
        context["idfamille"] = idfamille
        context["representants"] = representants
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        idfamille = self.kwargs["idfamille"]
        id_parent = request.POST.get("id_parent")

        if not id_parent:
            messages.error(request, "Veuillez sélectionner un parent.")
            return HttpResponseRedirect(reverse("famille_separer", kwargs={"idfamille": idfamille}))

        famille_origine = get_object_or_404(Famille, pk=idfamille)
        parent = get_object_or_404(Individu, pk=id_parent)

        # Détermine s'il y a un titulaire unique parmi les représentants, avant séparation
        ratt_representants = list(Rattachement.objects.filter(famille=famille_origine, categorie=1))
        ids_titulaires = [r.individu_id for r in ratt_representants if r.titulaire]
        titulaire_unique_id = ids_titulaires[0] if len(ids_titulaires) == 1 else None

        # Créer la nouvelle famille
        nouvelle_famille = Famille()
        nouvelle_famille.mode_separation = "force"
        nouvelle_famille.save()

        # Déplacer le parent vers la nouvelle famille
        Rattachement.objects.filter(famille=famille_origine, individu=parent).delete()
        Rattachement.objects.create(individu=parent, famille=nouvelle_famille, categorie=1, titulaire=True)

        # Copier les enfants dans la nouvelle famille
        enfants = Rattachement.objects.filter(famille=famille_origine, categorie=2)
        ids_enfants = []
        for ratt_enfant in enfants:
            Rattachement.objects.create(
                individu=ratt_enfant.individu,
                famille=nouvelle_famille,
                categorie=2,
                titulaire=False,
            )
            ids_enfants.append(ratt_enfant.individu_id)

        # Migration des prestations non facturées : suivent le parent qui part si c'est lui
        # le bénéficiaire direct, ou si c'est un enfant partagé dont le parent qui part est
        # l'unique titulaire du dossier. Sinon (ambigu), la prestation reste dans l'ancienne
        # famille par défaut - à réattribuer manuellement par l'agent si besoin.
        nb_prestations_migrees = 0
        ids_prestations_migrees = []
        prestations_non_facturees = Prestation.objects.filter(famille=famille_origine, facture__isnull=True)
        for prestation in prestations_non_facturees:
            migrer = False
            if prestation.individu_id == parent.pk:
                migrer = True
            elif prestation.individu_id in ids_enfants and titulaire_unique_id == parent.pk:
                migrer = True

            if migrer:
                prestation.famille = nouvelle_famille
                prestation.save()
                nb_prestations_migrees += 1
                ids_prestations_migrees.append(prestation.pk)

        # Les déductions suivent automatiquement la prestation à laquelle elles sont attachées
        if ids_prestations_migrees:
            Deduction.objects.filter(prestation_id__in=ids_prestations_migrees).update(famille=nouvelle_famille)

        # Migration des inscriptions du parent qui part, pour que ses futures réservations
        # soient bien rattachées à sa nouvelle famille
        Inscription.objects.filter(famille=famille_origine, individu=parent).update(famille=nouvelle_famille)

        # Migration des données liées à un individu précis (notes, contacts d'urgence, mandats,
        # assurances...) : même règle que pour les prestations.
        for model in MODELES_A_MIGRER_PAR_INDIVIDU:
            _migrer_donnees_individu(model, famille_origine, nouvelle_famille, parent, ids_enfants, titulaire_unique_id)

        # Si plus aucun titulaire ne reste dans l'ancienne famille (le parent qui part
        # était l'unique titulaire), on promeut automatiquement les représentants restants
        if not Rattachement.objects.filter(famille=famille_origine, categorie=1, titulaire=True).exists():
            Rattachement.objects.filter(famille=famille_origine, categorie=1).update(titulaire=True)

        # Marquer les deux familles
        famille_origine.mode_separation = "force"
        famille_origine.save()
        famille_origine.Maj_infos()
        nouvelle_famille.Maj_infos()

        message = f"Famille séparée. Nouvelle famille créée pour {parent.prenom} {parent.nom}."
        if nb_prestations_migrees:
            message += f" {nb_prestations_migrees} prestation(s) non facturée(s) migrée(s) vers la nouvelle famille."
        messages.success(request, message)
        return HttpResponseRedirect(reverse("famille_resume", kwargs={"idfamille": nouvelle_famille.pk}))
