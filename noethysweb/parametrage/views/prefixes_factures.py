# -*- coding: utf-8 -*-

#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import PrefixeFacture
from parametrage.forms.prefixes_factures import Formulaire



class Page(crud.Page):
    model = PrefixeFacture
    url_liste = "prefixes_factures_liste"
    url_ajouter = "prefixes_factures_ajouter"
    url_modifier = "prefixes_factures_modifier"
    url_supprimer = "prefixes_factures_supprimer"
    description_liste = "Voici ci-dessous la liste des préfixes de factures."
    description_saisie = "Saisissez toutes les informations concernant le préfixe à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "un préfixe de factures"
    objet_pluriel = "des préfixes de factures"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
    ]


class Liste(Page, crud.Liste):
    model = PrefixeFacture

    def get_queryset(self):
        return PrefixeFacture.objects.filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["idprefixe", "nom", "prefixe"]

        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idprefixe", "nom", "prefixe"]
            #hidden_columns = = ["idprefixe"]
            ordering = ['nom']


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire

class Modifier(Page, crud.Modifier):
    form_class = Formulaire

class Supprimer(Page, crud.Supprimer):
    pass
