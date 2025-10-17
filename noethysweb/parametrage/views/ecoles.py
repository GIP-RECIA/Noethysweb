# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Ecole, Organisateur
from parametrage.forms.ecoles import Formulaire, FormulaireENT
from core.utils.utils_ent import get_ent_ecole
from django.http import HttpResponseRedirect


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
    ]


class Liste(Page, crud.Liste):
    model = Ecole

    def get_queryset(self):
        return Ecole.objects.filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur and organisateur.ent_active:
            url_ajout = reverse_lazy("ecoles_ajouter_ent")
            context["boutons_liste"] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": url_ajout, "icone": "fa fa-plus"},
            ]
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["idecole", "nom", "rue", "cp", "ville", "uai"]

        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idecole", "nom", "rue", "cp", "ville", "uai"]
            ordering = ["nom"]

class AjouterEnt(Page, crud.Ajouter):
    form_class = FormulaireENT
    def form_valid(self, form):
        organisateur = Organisateur.objects.filter(pk=1).first()

        if organisateur and organisateur.ent_active:
            # ⚡ Appel API externe avec les données du formulaire
            uai = form.cleaned_data.get("uai")
            ecole_ent = get_ent_ecole(uai)
            secteurs = form.cleaned_data.get("secteurs")
            secteurs_ids = list(secteurs.values_list('idsecteur', flat=True)) if secteurs else []

            # Stocker le résultat dans la session (pour l’afficher après la redirection)
            
            self.request.session["ecole_ent"] = ecole_ent
            self.request.session["ecole_search_info"] = {
                "uai": uai,
                "secteurs": secteurs_ids
            }
            url_success = reverse_lazy("ecole_recherche_ent", kwargs={})
            # Rediriger vers une page dédiée (sans ajouter l'école)
            return HttpResponseRedirect(url_success)

            # Sinon, on garde le comportement classique (création de l'école)
        return super().form_valid(form)


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire

class Modifier(Page, crud.Modifier):
    form_class = Formulaire

class Supprimer(Page, crud.Supprimer):
    pass
