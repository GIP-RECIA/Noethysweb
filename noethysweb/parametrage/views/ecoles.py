# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect
from django.views.generic import TemplateView
from django.contrib import messages
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.views.base import CustomView
from core.models import Ecole
from core.utils.utils_ent import get_headers, get_school
from parametrage.forms.ecoles import Formulaire


class Page(crud.Page):
    model = Ecole
    url_liste = "ecoles_liste"
    url_ajouter = "ecoles_ajouter"
    url_modifier = "ecoles_modifier"
    url_supprimer = "ecoles_supprimer"
    description_liste = "Voici ci-dessous la liste des écoles."
    description_saisie = "Saisissez toutes les informations concernant l'école à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "une école"
    objet_pluriel = "des écoles"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
        {"label": "Importer depuis l'ENT", "classe": "btn btn-info", "href": reverse_lazy("ent_importer_ecole"), "icone": "fa fa-cloud-download"},
    ]


class Liste(Page, crud.Liste):
    model = Ecole

    def get_queryset(self):
        return Ecole.objects.filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["idecole", "nom", "rue", "cp", "ville"]

        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idecole", "nom", "rue", "cp", "ville"]
            ordering = ["nom"]


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire

class Modifier(Page, crud.Modifier):
    form_class = Formulaire

class Supprimer(Page, crud.Supprimer):
    pass


class ImporterEcoleEnt(CustomView, TemplateView):
    """
    Permet d'importer/actualiser une École Noethys à partir de son code UAI, en interrogeant
    directement Édifice (get_school) - plutôt que de laisser une École se créer à la volée,
    de façon peu fiable, au moment de l'import d'un élève.
    """
    template_name = "parametrage/ecoles_importer_ent.html"
    menu_code = "ecoles_liste"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Importer une école depuis l'ENT"
        context["box_titre"] = "Importer une école par UAI"
        context["box_introduction"] = "Saisissez le code UAI de l'établissement à importer ou actualiser."
        context["uai_recherche"] = kwargs.get("uai_recherche", "")
        context["erreur"] = kwargs.get("erreur")
        context["aucun_resultat"] = kwargs.get("aucun_resultat", False)
        context["resultat"] = kwargs.get("resultat")
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "rechercher")
        uai = request.POST.get("uai", "").strip()

        if action == "rechercher":
            if not uai:
                return self.render_to_response(self.get_context_data(erreur="Veuillez saisir un code UAI."))

            if get_headers() is None:
                return self.render_to_response(self.get_context_data(
                    uai_recherche=uai,
                    erreur="Impossible de se connecter à l'ENT. Vérifiez que la connexion est active et que les identifiants sont corrects, ou réessayez dans quelques instants (le service ENT peut être temporairement indisponible).",
                ))

            data = get_school(uai)
            if not data:
                return self.render_to_response(self.get_context_data(
                    uai_recherche=uai,
                    erreur=f"Aucun établissement trouvé pour le code UAI « {uai} ».",
                    aucun_resultat=True,
                ))

            # La clé "s.address" (avec un point) n'est pas lisible dans le template avec la
            # notation habituelle - on la recopie ici sous un nom simple.
            data["adresse"] = data.get("s.address")
            return self.render_to_response(self.get_context_data(uai_recherche=uai, resultat=data))

        # action == "importer" : on redemande les données à l'ENT plutôt que de faire confiance
        # à ce qui a transité par le formulaire, pour être sûr d'enregistrer des infos à jour.
        ent_id = request.POST.get("ent_id")
        if not ent_id:
            messages.error(request, "Donnée manquante, veuillez relancer la recherche.")
            return HttpResponseRedirect(reverse("ent_importer_ecole"))

        data = get_school(ent_id)
        if not data:
            messages.error(request, "Impossible de récupérer les informations de cette école, veuillez réessayer.")
            return HttpResponseRedirect(reverse("ent_importer_ecole"))

        ecole = Ecole.objects.filter(ent_id=ent_id).first()
        if not ecole and data.get("UAI"):
            ecole = Ecole.objects.filter(uai=data.get("UAI")).first()
        if not ecole:
            ecole = Ecole()

        ecole.nom = data.get("name") or ecole.nom or ent_id
        ecole.uai = data.get("UAI") or ecole.uai
        ecole.ent_id = ent_id
        ecole.ville = data.get("city") or ecole.ville
        ecole.cp = data.get("zipCode") or ecole.cp
        ecole.rue = data.get("s.address") or ecole.rue
        ecole.tel = data.get("phone") or ecole.tel
        ecole.mail = data.get("email") or ecole.mail
        ecole.save()

        messages.success(request, f"École « {ecole.nom} » importée/actualisée avec succès.")
        return HttpResponseRedirect(reverse("ecoles_liste"))
