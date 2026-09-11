import logging
import unicodedata
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from urllib.parse import urlencode

from core.views.base import CustomView
from core.models import (
    Individu, Famille, Rattachement, Prestation, Inscription, Deduction,
    Note, Piece, Historique, Destinataire, DestinataireSMS, QuestionnaireReponse,
    PortailRenseignement, ContactUrgence, Assurance, SondageRepondant, Cotisation, Mandat,
    Ecole, Classe, Scolarite,
)
from core.utils import utils_historique
from core.utils.utils_ent import search_by_name, search_users, get_user, get_headers, ent_est_actif
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)

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
        # _normaliser_texte (accents/casse) : même traitement que pour les noms et les
        # écoles ailleurs dans ce fichier - une rue identique écrite avec/sans accent ne
        # doit pas faire croire à deux adresses différentes.
        rue = _normaliser_texte(data.get("address") or "")
        cp = _normaliser_texte(data.get("zipCode") or "")
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


def _normaliser_texte(texte):
    """
    Enlève les accents et met en minuscules, pour comparer deux textes (noms d'école, noms de
    personnes...) de façon fiable. Nécessaire car nom__iexact (SQLite) n'ignore la casse que
    pour les lettres a-z sans accent - "École"/"école" ou "François"/"Francois" ne seraient
    sinon pas reconnus comme identiques.
    """
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return sans_accents.strip().lower()


def _trouver_ecole(ecole_nom, uai, ent_id=None):
    """
    Retrouve l'École Noethys correspondant à cette école ENT (par identifiant ENT en priorité -
    toujours présent -, puis par UAI, puis par nom, insensible à la casse) - ne crée jamais
    d'École. Renvoie None si elle n'est pas déjà connue de Noethys.

    Ne pas créer automatiquement est un choix délibéré (décision d'équipe) : une collectivité ne
    doit gérer que les écoles qu'elle connaît vraiment, importées explicitement via
    ImporterEcoleEnt (Paramétrage > Écoles) - jamais une école inconnue créée en douce à l'import
    ou à la synchronisation d'un élève.
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
    nom_normalise = _normaliser_texte(ecole_nom)
    ecole = next((e for e in Ecole.objects.all() if _normaliser_texte(e.nom) == nom_normalise), None)
    if ecole and ent_id and not ecole.ent_id:
        # Complète l'école déjà connue avec l'identifiant ENT si elle ne l'avait pas encore,
        # pour fiabiliser les prochaines correspondances.
        ecole.ent_id = ent_id
        ecole.save()
    return ecole


def _chercher_enfant_existant_non_lie(nom, prenom):
    """
    Cherche, par nom (insensible casse/accents), un enfant déjà présent dans Noethys mais
    jamais lié à l'ENT (ent_id vide) - contrairement à la vérification "déjà importé" de
    l'écran d'import, qui ne cherche que par ent_id et ne voit donc jamais une fiche saisie
    à la main avant l'arrivée de l'ENT. Sans cet appel, importer un tel enfant crée un
    doublon silencieux (2 fiches pour la même personne) au lieu de prévenir l'agent.
    Renvoie (individu, famille) ou (None, None).
    """
    if not nom or not prenom:
        return None, None
    nom_normalise, prenom_normalise = _normaliser_texte(nom), _normaliser_texte(prenom)
    candidats = Individu.objects.filter(Q(ent_id__isnull=True) | Q(ent_id=""), rattachement__categorie=2).distinct()
    for candidat in candidats:
        if _normaliser_texte(candidat.nom) == nom_normalise and _normaliser_texte(candidat.prenom or "") == prenom_normalise:
            ratt = Rattachement.objects.filter(individu=candidat, categorie=2).select_related("famille").first()
            return candidat, (ratt.famille if ratt else None)
    return None, None


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
    if not classe:
        # Repli insensible aux accents/casse, comme pour les écoles (_trouver_ecole) -
        # précaution : aucun doublon observé sur les données réelles testées, mais évite le
        # même risque qui avait touché les écoles avant leur fix (doublons faute de repli).
        nom_normalise = _normaliser_texte(classe_nom)
        classe = next((c for c in Classe.objects.filter(ecole=ecole) if _normaliser_texte(c.nom) == nom_normalise), None)
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
    Ne fait rien si l'ENT ne donne aucune école pour cet élève, ou si son école n'est pas
    déjà connue de Noethys (une Scolarité ne peut pas exister sans école, champ obligatoire -
    et on ne veut pas en créer une automatiquement, voir `_trouver_ecole`).
    """
    ecole_nom = eleve_data.get("ecole_nom")
    if not ecole_nom:
        return None

    ecole = _trouver_ecole(ecole_nom, eleve_data.get("ecole_uai"), eleve_data.get("ecole_ent_id"))
    if not ecole:
        return None

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


def _importer_eleve_ent(eleve_ent_id, eleve_data=None, parents_cache=None, lie_par=None):
    """
    Importe un élève et sa famille depuis l'ENT (logique partagée entre l'import unitaire
    et l'import en masse). `eleve_data` et `parents_cache` peuvent être fournis pré-chargés
    (récupérés en parallèle en amont) pour éviter de refaire les appels API un par un.
    `lie_par` trace qui a posé ce lien ENT : l'identifiant de l'agent pour un import unitaire
    (choisi et revu à l'écran), ou "auto" pour un import en masse (aucune revue individuelle).
    Retourne un dict {"statut": "importe"|"deja_importe"|"erreur", "message": str, "famille_id": int|None,
    "type": "famille_existante"|"nouvelle_famille"|"nouvelle_famille_separee"|None}. Le champ "type" précise,
    quand statut="importe", si l'élève a rejoint une famille déjà créée (frère/soeur) ou si une nouvelle
    famille a été créée pour lui — utile pour ne pas confondre "élèves importés" et "familles créées"
    dans un résumé d'import en masse.
    """
    lie_le = timezone.now() if lie_par else None
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
            parents_data = []
            for parent_info in eleve_data.get("parents", []):
                parent_data = Get_parent_data(parent_info["id"])
                if parent_data:
                    parents_data.append((parent_info["id"], parent_data))

            # Individus ENT déjà connus dans Noethys (n'importe quelle catégorie - même un
            # simple Contact, ex: un grand-parent) : ne jamais en recréer un doublon plus bas.
            individus_existants = {}
            for ent_id_parent, parent_data in parents_data:
                parent = Individu.objects.filter(ent_id=ent_id_parent).first()
                if parent:
                    individus_existants[ent_id_parent] = parent

            # Un parent peut ne pas (encore/plus) avoir d'ent_id - délié, ou jamais rapproché -
            # mais correspondre quand même par son nom à un représentant déjà connu, À
            # CONDITION que le nom de l'ÉLÈVE corrobore aussi dans cette même famille (deux
            # signaux indépendants, jamais un seul, avant de réutiliser silencieusement une
            # fiche - même principe que le moteur de corroboration). Sans ça, délier un parent
            # (au lieu de l'enfant) puis réimporter créait le même doublon silencieux.
            individu_eleve_par_nom, famille_eleve_par_nom = _chercher_enfant_existant_non_lie(
                eleve_data.get("lastName", ""), eleve_data.get("firstName", "")
            )
            if individu_eleve_par_nom and famille_eleve_par_nom:
                representants_famille = Rattachement.objects.filter(famille=famille_eleve_par_nom, categorie=1).select_related("individu")
                for ent_id_parent, parent_data in parents_data:
                    if ent_id_parent in individus_existants:
                        continue
                    for ratt in representants_famille:
                        representant = ratt.individu
                        if (_normaliser_texte(representant.nom) == _normaliser_texte(parent_data.get("lastName", ""))
                                and _normaliser_texte(representant.prenom or "") == _normaliser_texte(parent_data.get("firstName", ""))):
                            # Retrouvé par nom seulement (pas encore d'ent_id) - on le lie
                            # maintenant, sinon il resterait délié malgré cet import réussi.
                            representant.ent_id = ent_id_parent
                            representant.ent_lie_par = lie_par
                            representant.ent_lie_le = lie_le
                            representant.save()
                            individus_existants[ent_id_parent] = representant
                            break

            # Parmi eux, seuls ceux réellement Représentants (catégorie 1) quelque part
            # permettent de rattacher l'enfant à une famille déjà existante - un individu qui
            # n'est que Contact ailleurs (ex: un grand-parent) n'a pas de famille "à lui" en
            # tant que responsable, le rattachement serait arbitraire.
            parents_representants = [
                p for p in individus_existants.values() if Rattachement.objects.filter(individu=p, categorie=1).exists()
            ]
            noms_contacts_reutilises = [
                f"{p.prenom} {p.nom}" for p in individus_existants.values() if p not in parents_representants
            ]

            # Si un parent est déjà reconnu, on sait dans quelle(s) famille(s) l'élève va
            # atterrir - avant de créer sa fiche, on vérifie si une fiche à son nom existe déjà,
            # non liée, dans une de ces familles précises (ex : élève délié puis réimporté, ou
            # fiche saisie à la main avant que son parent soit rapproché de l'ENT). Sans ça, on
            # créait un doublon silencieux au lieu de réutiliser la fiche existante.
            eleve_existant_reutilisable = None
            if parents_representants:
                nom_norm = _normaliser_texte(eleve_data.get("lastName", ""))
                prenom_norm = _normaliser_texte(eleve_data.get("firstName", ""))
                familles_cibles_ids = {
                    ratt.famille_id for parent in parents_representants
                    for ratt in Rattachement.objects.filter(individu=parent, categorie=1)
                }
                candidats = Individu.objects.filter(
                    Q(ent_id__isnull=True) | Q(ent_id=""),
                    rattachement__categorie=2, rattachement__famille_id__in=familles_cibles_ids,
                ).distinct()
                for candidat in candidats:
                    if _normaliser_texte(candidat.nom) == nom_norm and _normaliser_texte(candidat.prenom or "") == prenom_norm:
                        eleve_existant_reutilisable = candidat
                        break

            if eleve_existant_reutilisable:
                eleve = eleve_existant_reutilisable
                eleve.ent_id = eleve_ent_id
                eleve.ent_lie_par = lie_par
                eleve.ent_lie_le = lie_le
                eleve.save()
            else:
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
                    ent_lie_par=lie_par,
                    ent_lie_le=lie_le,
                )
                eleve.save()

            # Enregistre la scolarité (école/classe) de l'élève, indépendamment de la
            # situation familiale déterminée plus bas. Pour une fiche réutilisée, on met à jour
            # sa scolarité existante plutôt que d'en créer une deuxième.
            eleve_data = _normaliser_enfant(eleve_data)
            if eleve_existant_reutilisable:
                from fiche_individu.views.individu_ent import Appliquer_sync_ecole_classe
                Appliquer_sync_ecole_classe(eleve, eleve_data)
            else:
                _creer_scolarite(eleve, eleve_data)

            if parents_representants:
                # Au moins un parent existe déjà — ajouter l'enfant à ses familles (sans
                # dupliquer le rattachement si la fiche réutilisée y était déjà).
                familles_ajoutees = set()
                for parent in parents_representants:
                    for ratt in Rattachement.objects.filter(individu=parent, categorie=1):
                        if ratt.famille_id not in familles_ajoutees:
                            if not Rattachement.objects.filter(individu=eleve, famille=ratt.famille).exists():
                                Rattachement.objects.create(individu=eleve, famille=ratt.famille, categorie=2, titulaire=False)
                            ratt.famille.Maj_infos()
                            familles_ajoutees.add(ratt.famille_id)
                famille_id = list(familles_ajoutees)[0]
                message = f"{eleve.prenom} {eleve.nom} rattaché(e) à sa fiche existante." if eleve_existant_reutilisable else f"{eleve.prenom} {eleve.nom} ajouté(e) à une famille existante."
                return {"statut": "importe", "message": message, "famille_id": famille_id, "type": "famille_existante"}

            def _note_contacts_reutilises():
                if not noms_contacts_reutilises:
                    return ""
                noms = ", ".join(noms_contacts_reutilises)
                if len(noms_contacts_reutilises) == 1:
                    return f" Note : {noms} était déjà connu(e) (Contact d'une autre famille) et a été rattaché(e) comme représentant(e) de cette nouvelle famille."
                return f" Note : {noms} étaient déjà connus (Contact d'une autre famille) et ont été rattachés comme représentants de cette nouvelle famille."

            def _get_ou_creer_parent(ent_id_parent, parent_data):
                """Réutilise la fiche existante (trouvée par ent_id) plutôt que d'en créer une
                deuxième - sinon un individu déjà connu (même simple Contact ailleurs) se
                retrouverait dupliqué, avec 2 fiches portant le même ent_id."""
                parent = individus_existants.get(ent_id_parent)
                if parent:
                    return parent
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
                    ent_lie_par=lie_par,
                    ent_lie_le=lie_le,
                )
                parent.save()
                return parent

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
                    parent = _get_ou_creer_parent(ent_id_parent, parent_data)
                    Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
                    Rattachement.objects.create(individu=eleve, famille=famille, categorie=2, titulaire=False)
                    famille.Maj_infos()
                return {"statut": "importe", "message": f"{eleve.prenom} {eleve.nom} importé(e), 2 familles séparées créées.{_note_contacts_reutilises()}", "famille_id": premiere_famille_id, "type": "nouvelle_famille_separee"}

            else:
                # Famille unique
                famille = Famille()
                famille.save()
                Rattachement.objects.create(individu=eleve, famille=famille, categorie=2, titulaire=False)
                for ent_id_parent, parent_data in parents_data:
                    parent = _get_ou_creer_parent(ent_id_parent, parent_data)
                    Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
                famille.Maj_infos()
                return {"statut": "importe", "message": f"{eleve.prenom} {eleve.nom} importé(e).{_note_contacts_reutilises()}", "famille_id": famille.pk, "type": "nouvelle_famille"}
    except Exception:
        # Le détail technique (message + trace complète) part dans les logs serveur, pas à
        # l'écran - un message brut ("list index out of range"...) n'apprend rien à l'agent
        # et masque un vrai bug derrière ce qui ressemble à une erreur ENT ordinaire.
        logger.exception("Erreur lors de l'import de l'élève ENT %s", eleve_ent_id)
        return {"statut": "erreur", "message": "Erreur technique lors de l'import - contactez le support si le problème persiste.", "famille_id": None, "type": None}


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
        context["nb_masques_ecole_inconnue"] = kwargs.get("nb_masques_ecole_inconnue", 0)
        return context

    def get(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))

        # Lire les résultats depuis la session puis les effacer
        resultats = request.session.pop("ent_resultats", None)
        last_name = request.session.pop("ent_last_name", "")
        first_name = request.session.pop("ent_first_name", "")
        erreur = request.session.pop("ent_erreur", None)
        nb_masques_ecole_inconnue = request.session.pop("ent_nb_masques_ecole_inconnue", 0)

        return self.render_to_response(self.get_context_data(
            resultats=resultats,
            last_name=last_name,
            first_name=first_name,
            erreur=erreur,
            nb_masques_ecole_inconnue=nb_masques_ecole_inconnue,
        ))

    def post(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))

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

        # Vérifie la connexion avant la recherche (credentials absents, ENT désactivé...) :
        # message explicite plutôt qu'un "Aucun résultat" trompeur. Une panne survenant APRÈS
        # ce test, en cours d'appel, est rattrapée juste en dessous (search_by_name renvoie
        # None dans ce cas, distinct de la liste vide "l'ENT ne connaît personne").
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
        nb_masques_ecole_inconnue = 0
        for enfant in familles.values():
            # École pas encore importée dans Noethys - une collectivité ne doit voir/gérer que
            # les écoles qu'elle connaît vraiment (décision d'équipe, voir _trouver_ecole). Ne
            # s'applique que si l'ENT donne bien une école pour cet élève (sinon rien à
            # vérifier). Masqué entièrement, pas juste bloqué à l'import - même règle et même
            # comportement que l'import en masse (ImporterEnMasseEnt) : remonter une fiche
            # bloquée reviendrait déjà à donner une information sur un enfant hors du périmètre
            # de l'organisateur, ce que la règle interdit précisément.
            if enfant.get("ecole_nom") and not _trouver_ecole(
                enfant.get("ecole_nom"), enfant.get("ecole_uai"), enfant.get("ecole_ent_id")
            ):
                nb_masques_ecole_inconnue += 1
                continue

            # Vérifier si déjà importé
            individu_existant = Individu.objects.filter(ent_id=enfant["id"]).first()
            if individu_existant:
                ratt = Rattachement.objects.filter(individu=individu_existant, categorie=2).first()
                enfant["deja_importe"] = True
                enfant["famille_id"] = ratt.famille_id if ratt else None
            else:
                enfant["deja_importe"] = False
                enfant["famille_id"] = None

            # Avertir si une fiche du même nom existe déjà dans Noethys SANS lien ENT (saisie
            # à la main avant l'arrivée de l'ENT, ou jamais rapprochée) - la vérification
            # "déjà importé" ci-dessus ne la voit pas, puisqu'elle ne cherche que par ent_id.
            # Sans cet avertissement, importer créait un doublon silencieux.
            enfant["fiche_existante_msg"] = None
            enfant["fiche_existante_famille_id"] = None
            if not enfant["deja_importe"]:
                individu_non_lie, famille_non_liee = _chercher_enfant_existant_non_lie(enfant.get("lastName"), enfant.get("firstName"))
                if individu_non_lie:
                    enfant["fiche_existante_famille_id"] = famille_non_liee.pk if famille_non_liee else None
                    enfant["fiche_existante_msg"] = (
                        f"Attention : une fiche « {individu_non_lie.prenom} {individu_non_lie.nom} » existe déjà"
                        f"{f' (famille {famille_non_liee.nom})' if famille_non_liee else ''}, sans lien ENT. "
                        f"Vérifiez qu'il ne s'agit pas de la même personne avant d'importer, sinon vous créerez un doublon."
                    )

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

            # Vérifier si les parents existent déjà dans Noethysweb - uniquement ceux qui sont
            # réellement Représentants (catégorie 1) quelque part : un individu qui n'existe
            # que comme Contact (ex: un grand-parent) n'a pas de famille "à lui" en tant que
            # responsable, ce message afficherait sinon "sera ajouté à la famille ." (vide) -
            # même règle que dans _importer_eleve_ent, qui décide réellement où l'enfant ira.
            enfant["parents_existants"] = False
            enfant["parents_existants_msg"] = None
            if not enfant["deja_importe"]:
                parents_representants_en_base = []
                for parent in enfant.get("parents", []):
                    if parent.get("id"):
                        p = Individu.objects.filter(ent_id=parent["id"]).first()
                        if p and Rattachement.objects.filter(individu=p, categorie=1).exists():
                            parents_representants_en_base.append(p)
                if parents_representants_en_base:
                    enfant["parents_existants"] = True
                    noms = " et ".join([f"{p.prenom} {p.nom}" for p in parents_representants_en_base])
                    familles_parents = Rattachement.objects.filter(
                        individu__in=parents_representants_en_base, categorie=1
                    ).select_related("famille").values_list("famille__nom", flat=True).distinct()
                    noms_familles = ", ".join(familles_parents)
                    if len(familles_parents) > 1:
                        enfant["parents_existants_msg"] = f"Les parents {noms} existent déjà (familles séparées). {enfant.get('firstName', '')} sera ajouté aux familles {noms_familles}."
                    else:
                        enfant["parents_existants_msg"] = f"Les parents {noms} existent déjà. {enfant.get('firstName', '')} sera ajouté à la famille {noms_familles}."

            resultats.append(enfant)

        request.session["ent_nb_masques_ecole_inconnue"] = nb_masques_ecole_inconnue

        if not resultats:
            # Soit rien n'a été trouvé, soit tout a été masqué (école(s) non reconnue(s)) - dans
            # les deux cas l'agent doit comprendre pourquoi la liste est vide, pas juste la voir
            # disparaître.
            if nb_masques_ecole_inconnue:
                request.session["ent_erreur"] = (
                    f"{nb_masques_ecole_inconnue} résultat(s) masqué(s) : "
                    f"école(s) pas encore importée(s) (Paramétrage > Écoles > Importer depuis l'ENT)."
                )
            else:
                request.session["ent_erreur"] = f"Aucune famille trouvée pour « {first_name} {last_name} » dans l'ENT."
            return

        request.session["ent_resultats"] = resultats

    def _importer(self, request):
        eleve_ent_id = request.POST.get("eleve_ent_id")
        if not eleve_ent_id:
            messages.error(request, "Données manquantes.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        eleve_data = get_user(eleve_ent_id)
        if not eleve_data:
            messages.error(request, "Impossible de récupérer les données de cet élève depuis l'ENT.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        eleve_data = _normaliser_enfant(eleve_data)
        if eleve_data.get("ecole_nom") and not _trouver_ecole(eleve_data.get("ecole_nom"), eleve_data.get("ecole_uai"), eleve_data.get("ecole_ent_id")):
            messages.error(request, f"Impossible d'importer : l'école « {eleve_data['ecole_nom']} » n'est pas encore importée (Paramétrage > Écoles > Importer depuis l'ENT).")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        resultat = _importer_eleve_ent(eleve_ent_id, eleve_data=eleve_data, lie_par=request.user.username)

        if resultat["statut"] == "deja_importe":
            messages.warning(request, "Cet élève a déjà été importé.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))
        elif resultat["statut"] == "erreur":
            messages.error(request, resultat["message"])
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))
        else:
            messages.success(request, resultat["message"])
            return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": resultat["famille_id"]}))


class PreLiaisonEnt(CustomView, TemplateView):
    """
    A utiliser avant l'import en masse : pour chaque enfant déjà présent dans Noethys mais pas
    encore lié à l'ENT, relance la même recherche que l'outil "Lier à un compte ENT" (par nom,
    avec comparaison des parents dans la même famille). Une fois les correspondances trouvées
    confirmées par l'agent, l'import en masse (inchangé) reconnaît automatiquement la famille
    existante et ses membres déjà connus, au lieu d'en créer des doublons.

    Part des individus déjà présents dans Noethys (pas de tout l'ENT) : bien plus rapide (un
    appel par enfant à lier, pas par élève de tout l'ENT), et réutilise une logique de
    comparaison déjà testée plutôt que d'en réécrire une nouvelle.

    La recherche (coûteuse - un appel ENT par enfant non lié) n'est lancée que sur demande
    explicite, et son résultat est gardé en session : confirmer une liaison ne fait que retirer
    la ligne correspondante de cette liste déjà connue, sans jamais relancer de recherche.
    """
    template_name = "fiche_famille/famille_ent_preliaison.html"
    menu_code = "famille_liste"
    SESSION_KEY = "ent_preliaison_groupes"

    def _rechercher_toutes_correspondances(self):
        """
        Lance la recherche complète et renvoie (groupes, non_resolus) - deux listes ne contenant
        que des types simples (str/int), pas d'objets Django, pour pouvoir être stockées en
        session. "non_resolus" liste, par famille, les personnes (enfants ET parents) que la
        recherche automatique n'a pas su traiter (avec la raison + un lien direct vers leur
        fiche) - pour que l'agent sache lesquelles vérifier à la main avant l'import en masse
        (sinon elles risquent d'être importées en double).
        """
        from fiche_individu.views.individu_ent import LierCompteEnt
        chercheur = LierCompteEnt()

        groupes_par_famille = {}  # {famille_id: {"famille_id":..., "famille_nom":..., "lignes":[...], "cles":{...}}}
        non_resolus_par_famille = {}  # {famille_id: {"famille_id":..., "famille_nom":..., "personnes":[{...}]}}
        enfants = Individu.objects.filter(Q(ent_id__isnull=True) | Q(ent_id=""), rattachement__categorie=2).distinct()

        def _ajouter_non_resolu(famille_pk, famille_nom, nom, individu_id, raison, role="Enfant"):
            """Signale une personne (enfant ou parent) que la recherche n'a pas su traiter."""
            groupe = non_resolus_par_famille.setdefault(famille_pk, {"famille_id": famille_pk, "famille_nom": famille_nom, "personnes": []})
            groupe["personnes"].append({"nom": nom, "individu_id": individu_id, "raison": raison, "role": role})

        def _ajouter_enfant_non_resolu(famille, enfant, raison):
            _ajouter_non_resolu(famille.pk, famille.nom, str(enfant), enfant.pk, raison, role="Enfant")

        # Phase 1 : détermine la famille de chaque enfant (rapide, en local)
        candidats = []
        for enfant in enfants:
            ratt = Rattachement.objects.filter(individu=enfant, categorie=2).select_related("famille").first()
            if ratt:
                candidats.append((enfant, ratt.famille))

        # Phase 2 : lance les recherches vers l'ENT en parallèle (5 à la fois) - la partie lente,
        # un enfant non lié = un appel API, potentiellement des centaines en une fois.
        def _chercher_un(candidat):
            enfant, famille = candidat
            resultats, erreur = chercheur._rechercher(enfant.nom, enfant.prenom, famille.pk, enfant.pk)
            return enfant, famille, resultats, erreur

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            resultats_recherche = list(executor.map(_chercher_un, candidats))

        # Phase 3 : traite les résultats (rapide, en local, pas d'appel API/DB supplémentaire)
        for enfant, famille, resultats, erreur in resultats_recherche:
            # _rechercher() renvoie toujours une erreur explicite dès que resultats est vide
            # (connexion impossible ou aucun résultat) - on réutilise directement ce message
            # plutôt que d'en deviner un nous-mêmes (les deux cas donnent juste "erreur rempli").
            if erreur:
                _ajouter_enfant_non_resolu(famille, enfant, erreur)
                continue

            # Le nom de l'enfant seul ne suffit pas à être sûr que l'ENT connaît "notre" enfant
            # (risque d'homonyme avec un enfant d'une autre famille/commune) - il faut qu'au moins
            # un parent le confirme, OU que sa date de naissance corresponde (voir "aucune_
            # corroboration"/"date_coherente" calculés dans _rechercher()). Si l'ENT renvoie
            # plusieurs élèves du même nom, on ne garde que ceux corroborés - s'il n'y en a qu'un
            # seul comme ça, pas d'ambiguïté réelle même si l'ENT en a renvoyé plusieurs. Si
            # plusieurs candidats corroborent chacun, là c'est une vraie ambiguïté - on abandonne,
            # l'agent pourra le faire à la main si besoin.
            candidats_corrobores = [r for r in resultats if not r.get("aucune_corroboration", True)]
            if len(candidats_corrobores) == 0:
                # Si un candidat a été rejeté PARCE QUE sa date de naissance contredit (alors
                # qu'un nom de parent correspondait), on réutilise le message précis déjà
                # calculé - dire "aucun parent ne correspond" serait faux et contradictoire
                # avec ce que l'agent verra en cliquant sur "Vérifier/lier".
                contradiction_date = next((r for r in resultats if r.get("nom_corrobore") and r.get("date_coherente") is False), None)
                if contradiction_date and contradiction_date.get("message_avertissement"):
                    _ajouter_enfant_non_resolu(famille, enfant, contradiction_date["message_avertissement"])
                else:
                    _ajouter_enfant_non_resolu(famille, enfant, "Trouvé dans l'ENT, mais aucun parent ne correspond")
                continue
            if len(candidats_corrobores) > 1:
                _ajouter_enfant_non_resolu(famille, enfant, "Plusieurs correspondances possibles dans l'ENT (ambigu)")
                continue

            resultat = candidats_corrobores[0]

            # Le compte ENT du candidat est-il déjà utilisé par un autre individu Noethys ?
            # Dans ce cas la confirmation échouerait silencieusement - on écarte l'enfant
            # dès maintenant, avec une raison claire (fiche en double probable).
            detenteur = resultat.get("compte_deja_utilise_par")
            if detenteur:
                _ajouter_enfant_non_resolu(famille, enfant, f"Le compte ENT correspondant est déjà utilisé par {detenteur} - vérifiez s'il s'agit d'une fiche en double")
                continue

            # Corroboré par la seule date de naissance (ou à défaut la seule école/classe), sans
            # qu'aucun parent ne corresponde : c'est la preuve la plus faible qu'on accepte.
            # Suffisant pour proposer un choix à un agent qui examine UN cas (écran individuel,
            # avec avertissement), mais pas pour une proposition automatique cochée d'avance au
            # milieu de centaines d'autres.
            if resultat.get("corrobore_par_date_seule"):
                _ajouter_enfant_non_resolu(famille, enfant, "Corroboré uniquement par la date de naissance, aucun parent ne correspond - à confirmer à la main")
                continue
            if resultat.get("corrobore_par_ecole_seule"):
                _ajouter_enfant_non_resolu(famille, enfant, "Corroboré uniquement par l'école et la classe, aucun parent ne correspond - à confirmer à la main")
                continue

            parents_enrichis = resultat.get("membres_enrichis", [])

            cle_enfant = f"{resultat['id']}|{enfant.pk}"
            lignes = [{
                "cle": cle_enfant,
                "nom_ent": f"{resultat.get('firstName', '')} {resultat.get('lastName', '')}",
                "nom_individu": str(enfant),
                "role": "Enfant",
                "date_coherente": resultat.get('date_coherente'),
                "ecole_coherente": resultat.get('ecole_coherente'),
            }]
            for parent in parents_enrichis:
                if parent["proposable"]:
                    lignes.append({
                        "cle": f"{parent['ent']['id']}|{parent['individu_correspondant'].pk}",
                        "nom_ent": f"{parent['ent'].get('firstName', '')} {parent['ent'].get('lastName', '')}",
                        "nom_individu": str(parent["individu_correspondant"]),
                        "role": "Parent",
                        # Une ligne Parent n'existe que parce que CET enfant a permis de la
                        # proposer - mémorisé pour pouvoir la retirer plus tard si l'enfant est
                        # écarté (voir phase 5), sans pénaliser un parent encore justifié par un
                        # frère/soeur dont la correspondance reste valable.
                        "vient_de": cle_enfant,
                    })

            groupe = groupes_par_famille.setdefault(famille.pk, {"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": [], "cles": set()})
            for ligne in lignes:
                if ligne["cle"] not in groupe["cles"]:
                    nouvelle_ligne = {"cle": ligne["cle"], "nom_ent": ligne["nom_ent"], "nom_individu": ligne["nom_individu"], "role": ligne["role"]}
                    if ligne["role"] == "Enfant":
                        nouvelle_ligne["date_coherente"] = ligne.get("date_coherente")
                        nouvelle_ligne["ecole_coherente"] = ligne.get("ecole_coherente")
                    else:
                        nouvelle_ligne["justifiee_par"] = []
                    groupe["lignes"].append(nouvelle_ligne)
                    groupe["cles"].add(ligne["cle"])
                if ligne["role"] == "Parent":
                    # Cas de la fratrie : ce même parent peut être proposé via plusieurs enfants
                    # de la famille - on accumule chaque enfant qui le justifie, que la ligne
                    # vienne d'être créée ci-dessus ou qu'elle existe déjà pour un enfant précédent.
                    ligne_deja_la = next(l for l in groupe["lignes"] if l["cle"] == ligne["cle"])
                    if ligne["vient_de"] not in ligne_deja_la["justifiee_par"]:
                        ligne_deja_la["justifiee_par"].append(ligne["vient_de"])

        # Phase 4 : détecte les collisions entre familles - si le même compte ENT se retrouve
        # proposé à des personnes Noethys différentes (2 familles distinctes qui se ressemblent
        # trop par coïncidence, même nom d'enfant ET de parent), c'est une vraie ambiguïté : on
        # retire ces lignes de partout, plutôt que de laisser une des deux familles "gagner" au
        # hasard sans que l'agent le sache (même logique que l'ambiguïté ENT, juste côté Noethys).
        ent_id_vers_individus = {}
        for groupe in groupes_par_famille.values():
            for ligne in groupe["lignes"]:
                ent_id, individu_pk = ligne["cle"].split("|", 1)
                ent_id_vers_individus.setdefault(ent_id, set()).add(individu_pk)
        ent_ids_en_collision = {ent_id for ent_id, individus in ent_id_vers_individus.items() if len(individus) > 1}

        # Départage automatique (demandé par l'équipe) : uniquement pour les enfants (un même
        # compte ENT élève proposé à 2 familles Noethys différentes - le cas typique d'homonymes).
        # Si une seule des familles en collision a une date de naissance cohérente avec ce compte
        # ENT (les autres non, ou inconnue), on la retient sans avertissement - la date de
        # naissance est une preuve individuelle bien plus fiable qu'un nom qui peut se répéter par
        # coïncidence entre 2 familles. Si la date ne suffit pas à trancher (aucune ne correspond,
        # ou plusieurs), on retente avec l'école/classe en dernier recours (plus faible - elle
        # change chaque année - mais toujours mieux que de tout laisser à la main). Les parents en
        # collision ne sont jamais départagés ainsi : une collision de parents signale presque
        # toujours une vraie fiche en double côté Noethys, pas une ambiguïté à trancher.
        ent_ids_departages = {}  # {ent_id: individu_pk retenu}
        for ent_id in ent_ids_en_collision:
            lignes_enfant_en_collision = [
                ligne
                for groupe in groupes_par_famille.values()
                for ligne in groupe["lignes"]
                if ligne["role"] == "Enfant" and ligne["cle"].split("|", 1)[0] == ent_id
            ]
            if len(lignes_enfant_en_collision) < 2:
                continue  # collision due uniquement aux parents, rien à départager ici
            for critere in ("date_coherente", "ecole_coherente"):
                gagnants = [l for l in lignes_enfant_en_collision if l.get(critere) is True]
                if len(gagnants) == 1:
                    ent_ids_departages[ent_id] = gagnants[0]["cle"].split("|", 1)[1]
                    break

        # Avant de les retirer, note les personnes perdues à cause d'une collision - sinon elles
        # disparaîtraient de partout, sans que l'agent sache qu'il faut les vérifier à la main.
        # Enfants ET parents : un parent en collision signale presque toujours une fiche en
        # double côté Noethys (deux fiches pour le même vrai parent, une par famille), et c'est
        # justement l'information utile à remonter - sinon elle se perd en silence.
        for famille_pk, groupe in groupes_par_famille.items():
            # Toutes les lignes en collision de cette famille (pas juste la première - 2 fiches
            # en double dans la même famille donneraient 2 lignes du même rôle ici).
            lignes_en_collision = [l for l in groupe["lignes"] if l["cle"].split("|", 1)[0] in ent_ids_en_collision]
            for ligne in lignes_en_collision:
                ent_id, individu_pk = ligne["cle"].split("|", 1)
                if ent_ids_departages.get(ent_id) == individu_pk:
                    continue  # départagée en sa faveur : reste dans les propositions automatiques
                if ligne["role"] == "Parent":
                    raison = "Ce parent correspond au même compte ENT qu'une autre fiche - probable fiche en double, à fusionner ou corriger"
                elif ent_id in ent_ids_departages:
                    raison = "Correspond au même compte ENT qu'une autre famille - départagé en faveur de l'autre famille par la date de naissance ou l'école/classe"
                else:
                    raison = "Correspond au même compte ENT qu'une autre famille (collision)"
                _ajouter_non_resolu(
                    famille_pk, groupe["famille_nom"],
                    ligne["nom_individu"], int(individu_pk),
                    raison, role=ligne["role"],
                )

        for groupe in groupes_par_famille.values():
            groupe["lignes"] = [
                l for l in groupe["lignes"]
                if l["cle"].split("|", 1)[0] not in ent_ids_en_collision
                or ent_ids_departages.get(l["cle"].split("|", 1)[0]) == l["cle"].split("|", 1)[1]
            ]

        # Phase 5 : une ligne Parent n'a jamais existé toute seule - elle n'a été proposée que
        # parce qu'au moins un enfant de la famille a permis de la corroborer (voir "vient_de"/
        # "justifiee_par" plus haut). Si TOUS les enfants qui la justifiaient viennent d'être
        # écartés ci-dessus (collision perdue, départage perdu...), la proposition sur ce parent
        # n'a plus aucun fondement et doit être retirée aussi - sinon on continuerait à proposer
        # de lier un parent à un compte ENT dont on vient de décider qu'il n'est pas le bon. À
        # l'inverse, tant qu'un seul enfant (fratrie) le justifie encore, on ne retire rien : le
        # priver de cette proposition serait injustifié, sa correspondance reste valable.
        for famille_pk, groupe in groupes_par_famille.items():
            cles_enfants_restants = {l["cle"] for l in groupe["lignes"] if l["role"] == "Enfant"}
            lignes_parent_orphelines = [
                l for l in groupe["lignes"]
                if l["role"] == "Parent" and l.get("justifiee_par")
                and not (set(l["justifiee_par"]) & cles_enfants_restants)
            ]
            for ligne in lignes_parent_orphelines:
                _ajouter_non_resolu(
                    famille_pk, groupe["famille_nom"],
                    ligne["nom_individu"], int(ligne["cle"].split("|", 1)[1]),
                    "Ce parent n'était proposé que via un enfant écarté entre-temps (collision "
                    "ou départage) - plus aucun enfant ne corrobore ce compte, à vérifier à la main",
                    role="Parent",
                )
            if lignes_parent_orphelines:
                cles_a_retirer = {l["cle"] for l in lignes_parent_orphelines}
                groupe["lignes"] = [l for l in groupe["lignes"] if l["cle"] not in cles_a_retirer]

        groupes_par_famille = {fid: g for fid, g in groupes_par_famille.items() if g["lignes"]}

        groupes = sorted(groupes_par_famille.values(), key=lambda g: g["famille_nom"])
        for groupe in groupes:
            del groupe["cles"]
            for ligne in groupe["lignes"]:
                ligne.pop("justifiee_par", None)

        non_resolus = sorted(non_resolus_par_famille.values(), key=lambda g: g["famille_nom"])
        return groupes, non_resolus

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Pré-liaison avant import en masse"
        context["box_titre"] = "Correspondances trouvées"
        context["box_introduction"] = "Lancez la recherche des membres de famille déjà présents qui correspondent à une famille connue par l'ENT, avant de lancer l'import en masse."
        context["erreur_connexion"] = False
        context["recherche_lancee"] = self.SESSION_KEY in self.request.session
        session_data = self.request.session.get(self.SESSION_KEY)
        # Garde-fou : une session encore au format d'avant ce changement (juste une liste, pas
        # un dict {groupes, non_resolus}) ne doit pas planter la page - traitée comme vide.
        if not isinstance(session_data, dict):
            session_data = {}
        context["groupes"] = session_data.get("groupes", [])
        context["non_resolus"] = session_data.get("non_resolus", [])
        context["nb_correspondances"] = sum(len(g["lignes"]) for g in context["groupes"])
        return context

    def get(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))

        action = request.POST.get("action", "confirmer")

        if action == "rechercher":
            if get_headers() is None:
                messages.error(request, "Impossible de se connecter à l'ENT. Vérifiez que la connexion est active et que les identifiants sont corrects, ou réessayez dans quelques instants (le service ENT peut être temporairement indisponible).")
            else:
                groupes, non_resolus = self._rechercher_toutes_correspondances()
                request.session[self.SESSION_KEY] = {"groupes": groupes, "non_resolus": non_resolus}
            return HttpResponseRedirect(reverse("ent_preliaison"))

        # action == "confirmer" : n'écrit qu'en base et met à jour la liste déjà en session -
        # ne relance jamais de recherche vers l'ENT.
        cles_confirmees = set(request.POST.getlist("liaisons_confirmees"))

        session_data = request.session.get(self.SESSION_KEY)
        if not isinstance(session_data, dict):
            session_data = {}
        groupes = session_data.get("groupes", [])

        # Nom tel qu'affiché à l'écran, pour pouvoir nommer précisément les lignes ignorées
        # (même libellé que celui que l'agent a coché, pas un recalcul).
        noms_par_cle = {ligne["cle"]: ligne["nom_individu"] for groupe in groupes for ligne in groupe["lignes"]}

        nb_lies = 0
        echecs = []  # [(nom, raison)] - jamais ignorer une ligne en silence : l'agent a coché,
                     # il doit savoir ce qui n'a pas été fait et pourquoi.
        deja_fait = []  # liaisons déjà en place à l'identique : ni succès, ni échec

        for cle in cles_confirmees:
            # Une clé qui ne fait pas partie des correspondances actuellement en session ne doit
            # jamais être liée. Deux cas réels : un formulaire périmé (l'agent a relancé la
            # recherche dans un autre onglet, puis confirmé l'ancien écran), ou une requête
            # envoyée directement. Sans ce contrôle, une ligne volontairement écartée - collision
            # entre 2 familles, ou famille perdante d'un départage - reste liable en rejouant le
            # POST, alors que c'est précisément la liaison qu'on refusait de proposer.
            if cle not in noms_par_cle:
                echecs.append(("Ligne inconnue", "ne fait pas partie des correspondances proposées, relancez la recherche"))
                continue
            nom = noms_par_cle[cle]
            try:
                ent_id, individu_pk = cle.split("|", 1)
            except ValueError:
                echecs.append((nom, "donnée illisible, relancez la recherche"))
                continue
            detenteur = Individu.objects.filter(ent_id=ent_id).first()
            if detenteur:
                # Cas fréquent depuis que "Vérifier/lier" ouvre un onglet : l'agent a déjà fait
                # cette liaison à côté. Le résultat voulu est atteint - ne pas l'annoncer comme
                # un échec, ce serait une fausse alerte.
                if str(detenteur.pk) == str(individu_pk):
                    deja_fait.append(nom)
                else:
                    echecs.append((nom, f"ce compte ENT est déjà utilisé par {detenteur}"))
                continue
            individu = Individu.objects.filter(pk=individu_pk).first()
            if not individu:
                echecs.append((nom, "cette fiche n'existe plus"))
                continue
            if individu.ent_id:
                echecs.append((nom, "déjà lié à un compte ENT entre-temps"))
                continue
            individu.ent_id = ent_id
            # L'agent, pas "auto" : il a coché explicitement cette ligne précise avant de
            # confirmer (contrairement à l'import en masse, qui ne montre aucune ligne
            # individuellement).
            individu.ent_lie_par = request.user.username
            individu.ent_lie_le = timezone.now()
            individu.save()
            nb_lies += 1

        nouveaux_groupes = []
        for groupe in groupes:
            lignes_restantes = [l for l in groupe["lignes"] if l["cle"] not in cles_confirmees]
            if lignes_restantes:
                groupe["lignes"] = lignes_restantes
                nouveaux_groupes.append(groupe)
        session_data["groupes"] = nouveaux_groupes
        request.session[self.SESSION_KEY] = session_data

        if nb_lies:
            messages.success(request, f"{nb_lies} individu(s) lié(s) à leur compte ENT. L'import en masse les reconnaîtra désormais automatiquement.")

        # Plafonné : avec des centaines de lignes cochées d'un coup, tout détailler donnerait
        # un message illisible.
        MAX_DETAIL = 10

        def _resumer(elements):
            detail = " ; ".join(elements[:MAX_DETAIL])
            if len(elements) > MAX_DETAIL:
                detail += f" ; et {len(elements) - MAX_DETAIL} autre(s)"
            return detail

        if deja_fait:
            messages.info(request, f"{len(deja_fait)} liaison(s) déjà en place, aucune action nécessaire : {_resumer(deja_fait)}.")

        if echecs:
            messages.warning(request, f"{len(echecs)} liaison(s) non effectuée(s) : {_resumer([f'{nom} ({raison})' for nom, raison in echecs])}.")

        if not nb_lies and not echecs and not deja_fait:
            messages.info(request, "Aucune liaison confirmée.")

        # Un seul log pour tout le lancement, pas une ligne par liaison confirmée - chaque
        # liaison individuelle est déjà tracée sur sa propre fiche (ent_lie_par/ent_lie_le).
        if cles_confirmees:
            detail = f"{nb_lies} liaison(s) créée(s), {len(echecs)} échec(s), {len(deja_fait)} déjà en place."
            utils_historique.Ajouter(titre="Confirmation de liaisons en pré-liaison ENT", detail=detail, utilisateur=request.user)

        return HttpResponseRedirect(reverse("ent_preliaison"))


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
        nb_masques_ecole_inconnue = 0
        if not context["erreur_connexion"]:
            eleves_bruts = search_users(profile="Student")
            # None = l'ENT n'a pas répondu (panne en cours d'appel, timeout), à ne pas confondre
            # avec une liste vide qui signifie "l'ENT a répondu qu'il n'a aucun élève".
            if eleves_bruts is None:
                context["erreur_connexion"] = True
                eleves_bruts = []
            for eleve_data in eleves_bruts:
                eleve_data = _normaliser_enfant(dict(eleve_data))
                # Ne montre que les élèves d'une école déjà connue de Noethys (même logique que
                # partout ailleurs, voir _trouver_ecole) - décision d'équipe : ne jamais remonter
                # des informations sur des enfants hors du périmètre de l'organisateur.
                ecole = _trouver_ecole(eleve_data.get("ecole_nom"), eleve_data.get("ecole_uai"), eleve_data.get("ecole_ent_id"))
                if not ecole:
                    nb_masques_ecole_inconnue += 1
                    continue

                individu_existant = Individu.objects.filter(ent_id=eleve_data.get("id")).first()
                eleve_data["deja_importe"] = individu_existant is not None
                if individu_existant:
                    ratt = Rattachement.objects.filter(individu=individu_existant, categorie=2).first()
                    eleve_data["famille_id"] = ratt.famille_id if ratt else None
                else:
                    eleve_data["famille_id"] = None
                eleves.append(eleve_data)

        context["eleves"] = eleves
        context["nb_masques_ecole_inconnue"] = nb_masques_ecole_inconnue
        context["nb_a_importer"] = sum(1 for e in eleves if not e["deja_importe"])
        return context

    def get(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))

        context = self.get_context_data()
        context["resume"] = request.session.pop("ent_import_masse_resume", None)
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return HttpResponseRedirect(reverse("famille_liste"))

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
            eleve_data = eleves_data.get(eleve_ent_id)

            # Revérifie l'école au moment du clic, pas seulement à l'affichage de la page
            # (celle-ci a pu rester ouverte un moment, ou l'école avoir été supprimée
            # entre-temps par un autre agent) - même contrôle que l'import unitaire, qui le
            # fait déjà à ce même instant, juste avant d'importer.
            if eleve_data:
                eleve_data_norm = _normaliser_enfant(dict(eleve_data))
                if eleve_data_norm.get("ecole_nom") and not _trouver_ecole(
                    eleve_data_norm.get("ecole_nom"), eleve_data_norm.get("ecole_uai"), eleve_data_norm.get("ecole_ent_id")
                ):
                    nb_erreurs += 1
                    erreurs_detail.append(
                        f"{eleve_data.get('firstName', '')} {eleve_data.get('lastName', '')} : "
                        f"école « {eleve_data_norm['ecole_nom']} » non reconnue (a peut-être été retirée entre-temps)"
                    )
                    continue

            # "auto" et non l'agent : l'import en masse traite potentiellement des centaines
            # d'élèves sans qu'aucun ne soit revu individuellement - contrairement à l'import
            # unitaire ci-dessus, où l'agent choisit et voit précisément qui il importe.
            resultat = _importer_eleve_ent(eleve_ent_id, eleve_data=eleve_data, parents_cache=parents_cache, lie_par="auto")
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

        # Un seul log pour tout le lancement, pas une ligne par élève importé - c'est
        # l'exécution de l'action qu'on trace ici, pas chaque élève individuellement (déjà
        # tracé sur sa propre fiche via ent_lie_par/ent_lie_le).
        detail = f"{nb_eleves_importes} élève(s) importé(s), {nb_ignores} déjà importé(s), {nb_erreurs} erreur(s)."
        if erreurs_detail:
            detail += " Erreurs : " + " ; ".join(erreurs_detail[:10])
            if len(erreurs_detail) > 10:
                detail += f" ; et {len(erreurs_detail) - 10} autre(s)"
        utils_historique.Ajouter(titre="Import en masse depuis l'ENT", detail=detail, utilisateur=request.user)

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

        # Traçabilité : la famille source va être supprimée, donc son nom/ID ne seront
        # plus retrouvables nulle part ensuite. C'est une action critique (factures,
        # règlements et payeur des deux familles regroupés sans distinction possible après
        # coup) - on garde une trace dans l'historique avant que ça disparaisse.
        detail = (
            f"Famille source : {famille_source.nom} (ID {famille_source.pk}). "
            f"Famille cible : {famille_cible.nom} (ID {famille_cible.pk})."
        )
        utils_historique.Ajouter(titre="Fusion de familles", detail=detail, utilisateur=request.user, famille=famille_cible.pk)

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

        # Migration des inscriptions : même règle que pour les prestations - celles du parent
        # qui part suivent toujours, celles d'un enfant partagé suivent seulement si le parent
        # qui part est l'unique titulaire du dossier (sinon ambigu, reste par défaut - à
        # réattribuer manuellement, voir ReattribuerInscription).
        Inscription.objects.filter(famille=famille_origine, individu=parent).update(famille=nouvelle_famille)
        if titulaire_unique_id == parent.pk and ids_enfants:
            Inscription.objects.filter(famille=famille_origine, individu_id__in=ids_enfants).update(famille=nouvelle_famille)

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
