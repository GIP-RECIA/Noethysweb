from datetime import date
from concurrent.futures import ThreadPoolExecutor
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db import transaction
from urllib.parse import urlencode

from core.views.base import CustomView
from core.models import Individu, Famille, Rattachement
from core.utils.utils_ent import search_by_name, get_user
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
    """Convertit la civilité ENT (texte) en ID Noethysweb."""
    mapping = {
        "M.": 1, "M": 1, "Mr": 1, "Monsieur": 1,
        "Mme": 3, "Madame": 3,
        "Melle": 2, "Mlle": 2, "Mademoiselle": 2,
    }
    return mapping.get(valeur, 1)


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
    """Ajoute ecole_nom et classe_nom selon le format retourné (admin/list ou get_user)."""
    # Ecole : admin/list -> structures[0].name | get_user -> structureNodes[0].name
    structures = data.get("structures") or []
    struct_nodes = data.get("structureNodes") or []
    if structures and isinstance(structures[0], dict):
        data["ecole_nom"] = structures[0].get("name")
    elif struct_nodes and isinstance(struct_nodes[0], dict):
        data["ecole_nom"] = struct_nodes[0].get("name")
    else:
        data["ecole_nom"] = None

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

    @transaction.atomic
    def _importer(self, request):
        eleve_ent_id = request.POST.get("eleve_ent_id")
        if not eleve_ent_id:
            messages.error(request, "Données manquantes.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        if Individu.objects.filter(ent_id=eleve_ent_id).exists():
            messages.warning(request, "Cet élève a déjà été importé.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        eleve_data = get_user(eleve_ent_id)
        if not eleve_data:
            messages.error(request, "Impossible de récupérer les données de l'élève depuis l'ENT.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        # Créer l'élève (une seule fois)
        eleve = Individu(
            nom=eleve_data.get("lastName", ""),
            prenom=eleve_data.get("firstName", ""),
            civilite=_convertir_civilite(eleve_data.get("title")),
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

        # Récupérer les données des parents
        parents_data = []
        for parent_info in eleve_data.get("parents", []):
            parent_data = get_user(parent_info["id"])
            if parent_data:
                parents_data.append((parent_info["id"], parent_data))

        # Vérifier si les parents existent déjà dans Noethysweb
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

            premiere_famille_id = list(familles_ajoutees)[0]
            noms_parents = " et ".join([f"{p.prenom} {p.nom}" for p in parents_existants])
            if len(familles_ajoutees) > 1:
                messages.success(request, f"{eleve.prenom} a été ajouté aux {len(familles_ajoutees)} familles de {noms_parents}.")
            else:
                messages.success(request, f"{eleve.prenom} a été ajouté à la famille existante de {noms_parents}.")
            return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": premiere_famille_id}))

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

            messages.success(request, "Deux familles séparées ont été créées automatiquement (adresses différentes).")
            return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": premiere_famille_id}))

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
            messages.success(request, "Famille importée avec succès.")
            return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": famille.pk}))


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

        # Supprimer la famille source
        famille_source.delete()

        # Réinitialiser le mode_separation
        famille_cible.mode_separation = None
        famille_cible.save()
        famille_cible.Maj_infos()

        messages.success(request, "Les deux familles ont été fusionnées avec succès.")
        return HttpResponseRedirect(reverse("famille_resume", kwargs={"idfamille": idfamille}))


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

        # Créer la nouvelle famille
        nouvelle_famille = Famille()
        nouvelle_famille.mode_separation = "force"
        nouvelle_famille.save()

        # Déplacer le parent vers la nouvelle famille
        Rattachement.objects.filter(famille=famille_origine, individu=parent).delete()
        Rattachement.objects.create(individu=parent, famille=nouvelle_famille, categorie=1, titulaire=True)

        # Copier les enfants dans la nouvelle famille
        enfants = Rattachement.objects.filter(famille=famille_origine, categorie=2)
        for ratt_enfant in enfants:
            Rattachement.objects.create(
                individu=ratt_enfant.individu,
                famille=nouvelle_famille,
                categorie=2,
                titulaire=False,
            )

        # Marquer les deux familles
        famille_origine.mode_separation = "force"
        famille_origine.save()
        famille_origine.Maj_infos()
        nouvelle_famille.Maj_infos()

        messages.success(request, f"Famille séparée. Nouvelle famille créée pour {parent.prenom} {parent.nom}.")
        return HttpResponseRedirect(reverse("famille_resume", kwargs={"idfamille": nouvelle_famille.pk}))
