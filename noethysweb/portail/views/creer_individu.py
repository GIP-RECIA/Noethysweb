# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime
logger = logging.getLogger(__name__)
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.http import HttpResponseRedirect
from django.contrib import messages
from core.views import crud
from core.models import Individu, Rattachement, PortailRenseignement
from core.utils import utils_questionnaires, utils_portail
from portail.forms.creer_individu import Formulaire
from portail.views.base import CustomView


class Page(CustomView):
    menu_code = "portail_renseignements"

    def test_func(self):
        # Vérifie que la création d'un individu est bien autorisée
        parametres_portail = utils_portail.Get_dict_parametres()
        if not parametres_portail.get("connexion_creation_compte", False) and not parametres_portail.get("renseignements_creation_individu", False):
            return False
        return True

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['page_titre'] = _("Saisir un nouvel individu")
        context['box_titre'] = None
        context['box_introduction'] = _("Renseignez les champs ci-dessous et cliquez sur le bouton Valider.")
        return context

    def get_success_url(self):
        return reverse_lazy("portail_renseignements")


class Ajouter(Page, crud.Ajouter):
    model = Individu
    form_class = Formulaire
    texte_confirmation = _("La demande a bien été transmise")
    titre_historique = "Saisir un nouvel individu"
    template_name = "portail/edit.html"

    def Get_detail_historique(self, instance):
        return "Famille=%s, Individu=%s" % (instance.famille, instance.individu)

    def form_valid(self, form):
        famille = self.request.user.famille

        # Sauvegarde de l'individu à créer
        self.object = form.save()
        self.object.memo = "Fiche individuelle créée sur le portail le %s." % datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        self.object.save()

        # Création des questionnaires de type individu
        utils_questionnaires.Creation_reponses(categorie="individu", liste_instances=[self.object])

        # Recherche d'une adresse à rattacher
        for rattachement in Rattachement.objects.prefetch_related("individu").filter(famille=famille):
            if not rattachement.individu.adresse_auto:
                self.object.adresse_auto = rattachement.individu.pk
                self.object.save()
                self.object.Maj_infos()
                break

        # Sauvegarde du rattachement
        rattachement = Rattachement(famille=famille, individu=self.object, categorie=form.cleaned_data["categorie"],
                                    titulaire=form.cleaned_data["titulaire"] if form.cleaned_data["categorie"] in (1, "1") else False)
        rattachement.save()

        # MAJ des infos de la famille
        famille.Maj_infos()

        # Mémorisation dans l'historique
        PortailRenseignement.objects.create(famille=famille, individu=self.object, categorie="nouvel_individu",
                                            code="Nouvelle fiche individuelle", idobjet=self.object.pk)

        # Message
        messages.add_message(self.request, messages.INFO, "Vous pouvez maintenant compléter les autres renseignements en cliquant sur cette fiche dans la liste au bas de cette page.")
        messages.add_message(self.request, messages.SUCCESS, "La fiche individuelle a bien été créée.")

        return HttpResponseRedirect(self.get_success_url())
