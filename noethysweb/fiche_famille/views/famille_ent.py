from datetime import date
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db import transaction
from urllib.parse import urlencode

from core.views.base import CustomView
from core.models import Individu, Famille, Rattachement
from core.utils.utils_ent import search_by_name, get_user

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

        for user in resultats_bruts:
            # L'endpoint /admin/list retourne le profil dans "type", pas "profiles"
            user_type = user.get("type") or ""

            if "Student" in user_type:
                # Résultat direct : c'est un élève
                enfant_data = get_user(user["id"])
                if enfant_data:
                    familles[enfant_data["id"]] = _normaliser_enfant(enfant_data)

            elif "Relative" in user_type:
                # C'est un parent : on récupère ses enfants
                parent_data = get_user(user["id"])
                if not parent_data:
                    continue
                for child in parent_data.get("children", []):
                    if not child.get("id"):
                        continue
                    if child["id"] not in familles:
                        enfant_data = get_user(child["id"])
                        if enfant_data:
                            familles[enfant_data["id"]] = _normaliser_enfant(enfant_data)

        if not familles:
            request.session["ent_erreur"] = f"Aucune famille trouvée pour « {first_name} {last_name} » dans l'ENT."
            return

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

            # Récupérer les détails des parents
            parents_details = []
            for parent in enfant.get("parents", []):
                if not parent.get("id"):
                    continue
                parent_data = get_user(parent["id"])
                if parent_data:
                    parents_details.append(parent_data)
            enfant["parents_details"] = parents_details

            resultats.append(enfant)

        request.session["ent_resultats"] = resultats

    @transaction.atomic
    def _importer(self, request):
        eleve_ent_id = request.POST.get("eleve_ent_id")
        if not eleve_ent_id:
            messages.error(request, "Données manquantes.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        # Vérifier si déjà importé
        if Individu.objects.filter(ent_id=eleve_ent_id).exists():
            messages.warning(request, "Cet élève a déjà été importé.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        # Récupérer les données de l'élève
        eleve_data = get_user(eleve_ent_id)
        if not eleve_data:
            messages.error(request, "Impossible de récupérer les données de l'élève depuis l'ENT.")
            return HttpResponseRedirect(reverse_lazy("ent_import_famille"))

        # Créer la famille
        famille = Famille()
        famille.save()

        # Créer l'élève
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
        Rattachement.objects.create(individu=eleve, famille=famille, categorie=2, titulaire=False)

        # Créer les parents
        for parent_info in eleve_data.get("parents", []):
            parent_data = get_user(parent_info["id"])
            if not parent_data:
                continue

            # Vérifier si ce parent existe déjà
            parent = Individu.objects.filter(ent_id=parent_info["id"]).first()
            if not parent:
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
                    ent_id=parent_info["id"],
                )
                parent.save()

            Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        # Mettre à jour le nom de la famille
        famille.Maj_infos()

        messages.success(request, f"Famille importée avec succès.")
        return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={"idfamille": famille.pk}))
