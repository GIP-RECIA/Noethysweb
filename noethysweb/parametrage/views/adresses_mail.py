# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json

import django.contrib.messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from core.models import AdresseMail
from core.views import crud
from core.views.base import CustomView
from core.views.mydatatableview import MyDatatable, columns
from outils.utils import utils_email
from parametrage.forms.adresse_mail_expedition import FormulaireEmailExpedition
from parametrage.forms.adresses_mail import Formulaire


def Envoyer_mail_test(request):
    # Récupère les paramètres de l'adresse d'expédition
    valeurs_form_adresse = json.loads(request.POST.get("form_adresse"))
    form_adresse = Formulaire(valeurs_form_adresse, request=request)
    if form_adresse.is_valid() == False:
        return JsonResponse({"erreur": "Veuillez compléter les paramètres de l'adresse d'expédition"}, status=401)

    # Récupère l'adresse de destination du test
    adresse_destination = request.POST.get("adresse_destination")
    if not adresse_destination:
        return JsonResponse({"erreur": "Veuillez saisir une adresse de destination pour le test d'envoi"}, status=401)

    # Met toutes les données dans un dict
    dict_options = form_adresse.cleaned_data
    dict_options.update({"adresse_destination": adresse_destination})

    # Envoi du message
    resultat = utils_email.Envoyer_mail_test(request=request, dict_options=dict_options)
    return JsonResponse({"resultat": resultat})


class Page(crud.Page):
    model = AdresseMail
    url_liste = "adresses_mail_liste"
    url_ajouter = "adresses_mail_ajouter"
    url_modifier = "adresses_mail_modifier"
    url_supprimer = "adresses_mail_supprimer"
    description_liste = "Voici ci-dessous la liste des adresses d'expédition d'emails."
    description_saisie = "Saisissez toutes les informations concernant l'adresse d'expédition à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "une adresse d'expédition"
    objet_pluriel = "des adresses d'expédition"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
    ]
    compatible_demo = False


class Liste(Page, crud.Liste):
    model = AdresseMail

    def get_queryset(self):
        return AdresseMail.objects.filter(self.Get_filtres("Q"), self.Get_condition_structure())

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ['idadresse', 'actif', 'adresse', 'moteur']
        adresse = columns.TextColumn("Adresse", sources=None, processor='Get_adresse')
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')
        actif = columns.TextColumn("Etat", sources=["actif"], processor='Get_actif')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ['idadresse', 'actif', 'adresse', 'moteur']
            ordering = ['adresse']

        def Get_adresse(self, instance, **kwargs):
            return instance.adresse

        def Get_default(self, instance, **kwargs):
            return "<i class='fa fa-check text-success'></i>" if instance.defaut else ""

        def Get_actif(self, instance, *args, **kwargs):
            return "<small class='badge badge-success'>Activée</small>" if instance.actif else "<small class='badge badge-danger'>Désactivée</small>"


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire


class Modifier(Page, crud.Modifier):
    form_class = Formulaire


class Supprimer(Page, crud.Supprimer):
    pass


class parametre_expedition_mail(CustomView, UserPassesTestMixin, TemplateView):
    template_name = "core/crud/edit.html"
    compatible_demo = False

    def test_func(self):
        # Permet l'accès uniquement aux superusers
        return self.request.user.is_superuser

    def handle_no_permission(self):
        # Message personnalisé si l'utilisateur n'est pas autorisé
        django.contrib.messages.error(self.request, "Accès réservé aux administrateurs.")
        return HttpResponseRedirect(reverse_lazy("parametrage_toc"))

    def get_context_data(self, **kwargs):
        context = super(parametre_expedition_mail, self).get_context_data(**kwargs)
        context['page_titre'] = "Paramètres Expedition d'emails"
        context['box_titre'] = "Paramètres"
        context['box_introduction'] = "Ajustez les paramètres d'expédition des emails pour parametrer les adresses d'expedition."
        context['form'] = FormulaireEmailExpedition()
        return context

    def post(self, request, **kwargs):
        form = FormulaireEmailExpedition(request.POST)
        if not form.is_valid():
            django.contrib.messages.error(request, 'Aucun paramétre coché!')
            return self.render_to_response(self.get_context_data(form=form))

        # Les données sont déjà enregistrées dans la méthode clean() du formulaire
        django.contrib.messages.success(request, 'Paramètres enregistrés')
        return HttpResponseRedirect(reverse_lazy("parametres_mail_expedition"))
