# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime
logger = logging.getLogger(__name__)
from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib import messages
from core.views.base import CustomView
from core.models import Utilisateur, Individu
from individus.forms.importer_individus_ent import Formulaire
from django.http import JsonResponse
from fiche_famille.utils import utils_internet

def ajouter_individu(request):
    if request.method == "POST":
        try:
            if Individu.objects.filter(ent_id=request.POST.get("entid")).exists():
                return JsonResponse({"success": False, "error": "Cet utilisateur existe déjà"})
            individu = Individu.objects.create(
                ent_id=request.POST.get("entid"),
                nom=request.POST.get("nom"),
                prenom=request.POST.get("prenom"),
                mail=request.POST.get("email"),
                date_naiss=request.POST.get("date_naissance"),
                rue_resid=request.POST.get("adresse"),
                ville_resid=request.POST.get("ville"),
                cp_resid=request.POST.get("codepostal"),
                tel_mobile=request.POST.get("telephone_portable"),
                tel_domicile=request.POST.get("telephone_domicile"),
                tel_fax=request.POST.get("telephone_fixe"),
            )
            internet_identifiant_individu = utils_internet.CreationIdentifiantIndividu(IDindividu=individu.pk)
            internet_mdp_individu, date_expiration_mdp_individu = utils_internet.CreationMDP()
            individu.internet_identifiant = internet_identifiant_individu
            individu.internet_mdp = internet_mdp_individu

            # Vous pouvez aussi créer un utilisateur pour l'individu si nécessaire
            utilisateur_individu = Utilisateur(
                username=internet_identifiant_individu,
                categorie="individu",  # Ou une autre catégorie, selon votre besoin
                force_reset_password=True,
                date_expiration_mdp=date_expiration_mdp_individu
            )
            utilisateur_individu.set_password(internet_mdp_individu)
            utilisateur_individu.save()

            # Association de l'utilisateur à l'individu
            individu.utilisateur = utilisateur_individu
            individu.save()
            return JsonResponse({"success": True, "id": individu.idindividu})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Méthode non autorisée"})


class View(CustomView, TemplateView):
    menu_code = "importer_individus_ent"
    template_name = "core/crud/edit.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Importer des individus de l'ENT"
        context['box_titre'] = "Effectuer une recherche des individus de L'ENT"
        context['box_introduction'] = "Saisissez un ou plusieurs critères de recherche et cliquez sur le bouton Rechercher."
        context['form'] = context.get("form", Formulaire)
        return context

    def post(self, request, **kwargs):
        # Validation du form
        form = Formulaire(request.POST, request.FILES, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # Champs de recherche
        champs_recherche = form.changed_data
        # Recherche des résultats
        import jellyfish

        resultats = {}
        # rattachements = Rattachement.objects.select_related("individu", "famille").all()
        # for rattachement in rattachements:
        #     score = resultats.get(rattachement, 0)
        #
        #     for nom_champ in champs_recherche:
        #         valeur_recherche = form.cleaned_data[nom_champ]
        #         valeur_individu = getattr(rattachement.individu, nom_champ, "")
        #
        #         # Recherche de texte
        #         if isinstance(valeur_individu, str):
        #             try:
        #                 distance = jellyfish.jaro_distance(valeur_recherche.lower(), valeur_individu.lower())
        #             except:
        #                 distance = jellyfish.jaro_similarity(valeur_recherche.lower(), valeur_individu.lower())
        #             score += distance
        #
        #             if score >= 0.75:
        #                 resultats[rattachement] = score
        #
        #         # Recherche de date
        #         if isinstance(valeur_individu, datetime.date):
        #             if valeur_recherche == valeur_individu:
        #                 resultats[rattachement] = score
        #
        # # Tri par score
        # resultats = sorted([(score, rattachement) for rattachement, score in resultats.items()], key=lambda donnees: donnees[0], reverse=True)
        resultats = [
                        {
                            "ent_id": "550e8400-e29b-41d4-a716-446655440000",
                            "civilite": "M.",
                            "nom": "Dupont",
                            "nom_usage": "Durand",
                            "prenom": "Jean",
                            "date_naissance": "1985-07-12",
                            "adresse": "12 Rue de la République Bâtiment A Appartement 45",
                            "ville": "Paris",
                            "code_postal": "75001",
                            "telephone_fixe": "+33 1 44 55 66 77",
                            "telephone_domicile": "+33 1 40 22 33 44",
                            "telephone_portable": "+33 6 12 34 56 78",
                            "email": "jean.dupont@example.com"
                        },
                        {
                            "ent_id": "660e8400-e29b-41d4-a716-446655440111",
                            "civilite": "Mme",
                            "nom": "Martin",
                            "nom_usage": "Leroy",
                            "prenom": "Sophie",
                            "date_naissance": "1990-03-25",
                            "adresse": "8 Avenue Victor Hugo",
                            "ville": "Lyon",
                            "code_postal": "69002",
                            "telephone_fixe": "+33 4 78 12 34 56",
                            "telephone_domicile": "+33 4 78 65 43 21",
                            "telephone_portable": "+33 6 98 76 54 32",
                            "email": "sophie.martin@example.com"
                        },
                        {
                            "ent_id": "770e8400-e29b-41d4-a716-446655440222",
                            "civilite": "M.",
                            "nom": "Bernard",
                            "nom_usage": "",
                            "prenom": "Paul",
                            "date_naissance": "1978-11-02",
                            "adresse": "35 Boulevard Saint-Michel",
                            "ville": "Marseille",
                            "code_postal": "13006",
                            "telephone_fixe": "+33 4 91 23 45 67",
                            "telephone_domicile": "+33 4 91 11 22 33",
                            "telephone_portable": "+33 6 33 44 55 66",
                            "email": "paul.bernard@example.com"
                        }
                    ]
        # Envoi des 50 premiers résultats
        context = self.get_context_data(**kwargs)
        context["resultats_ent"] = resultats[:50]  # pas besoin de [r[1] for r in ...]
        return render(request, "individus/importer_individus_ent.html", context)
