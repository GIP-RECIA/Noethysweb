# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime
logger = logging.getLogger(__name__)
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.urls import reverse_lazy
from django.db.models import Q
from django.utils.translation import gettext as _
from core.views import crud
from core.models import Consentement, Rattachement, Inscription
from individus.utils import utils_vaccinations, utils_assurances
from portail.views.base import CustomView
from portail.forms.approbations import Formulaire
from portail.utils import utils_champs


class View(CustomView, crud.Modifier):
    menu_code = "portail_renseignements"
    form_class = Formulaire
    template_name = "portail/renseignements.html"
    mode = "CONSULTATION"

    def get_form_kwargs(self):
        form_kwargs = super(View, self).get_form_kwargs()
        familles = self.get_famille_object()
        if familles:
            form_kwargs["familles"] = familles
        return form_kwargs

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = _("Renseignements")

        familles = self.get_famille_object()
        context["familles"] = familles

        def _build_data_for_famille(famille):
            data = {"famille": famille}

            # Rattachements (fiches individuelles)
            rattachements = Rattachement.objects.prefetch_related('individu').filter(
                famille=famille,
                individu__deces=False,
            ).exclude(
                individu__in=famille.individus_masques.all()
            ).order_by("individu__nom", "individu__prenom")
            data["rattachements"] = rattachements
            data["fiches"] = rattachements

            # Récupération des activités de la famille
            conditions = Q(famille=famille) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
            inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions)

            renseignements_manquants = {}

            # Recherche les informations manquantes
            for (famille_insc, individu), liste_vaccinations in utils_vaccinations.Get_vaccins_obligatoires_by_inscriptions(inscriptions=inscriptions).items():
                if famille_insc != famille:
                    continue
                renseignements_manquants.setdefault(individu, [])
                renseignements_manquants[individu].append("%d vaccination%s manquante%s" % (len(liste_vaccinations), "s" if len(liste_vaccinations) > 1 else "", "s" if len(liste_vaccinations) > 1 else ""))

            for individu in utils_assurances.Get_assurances_manquantes_by_inscriptions(famille=famille, inscriptions=inscriptions):
                renseignements_manquants.setdefault(individu, [])
                renseignements_manquants[individu].append("Assurance manquante")

            for individu, liste_infos_manquantes in utils_champs.Get_renseignements_manquants(famille=famille)["FICHES"].items():
                renseignements_manquants.setdefault(individu, [])
                nbre = len(liste_infos_manquantes)
                renseignements_manquants[individu].append("%d information%s manquante%s : %s" % (nbre, "s" if nbre > 1 else "", "s" if nbre > 1 else "", ", ".join(liste_infos_manquantes)))

            data["renseignements_manquants"] = renseignements_manquants
            data["approbations"] = []
            return data

        # -----------------------------
        # Données par famille (multi-famille)
        # -----------------------------
        donnees_par_famille = []
        for famille in familles:
            donnees_par_famille.append(_build_data_for_famille(famille))
        context["donnees_par_famille"] = donnees_par_famille

        return context

    def get_object(self):
        familles = self.get_famille_object()
        return familles[0] if familles else None

    def get_success_url(self):
        return reverse_lazy("portail_renseignements")

    def form_valid(self, form):
        """ Enregistrement des approbations """
        familles = self.get_famille_object()
        famille_principale = familles[0] if familles else None
        if not famille_principale:
            messages.add_message(self.request, messages.ERROR, _("Aucune famille n'est associée à ce compte"))
            return HttpResponseRedirect(self.get_success_url())

        # Enregistrement des approbations cochées
        nbre_coches = 0
        for code, coche in form.cleaned_data.items():
            if coche:
                if code.startswith("unite_"):
                    # format : unite_{fam_pk}_{unite_pk}
                    parts = code.split("_")
                    fam_pk, unite_pk = parts[1], parts[2]
                    Consentement.objects.create(famille_id=int(fam_pk), unite_consentement_id=int(unite_pk))
                    nbre_coches += 1
                elif code.startswith("rattachement_"):
                    idrattachement = int(code.replace("rattachement_", ""))
                    Rattachement.objects.filter(pk=idrattachement).update(certification_date=datetime.datetime.now())
                    nbre_coches += 1
                elif code.startswith("famille_"):
                    idfamille = int(code.replace("famille_", ""))
                    for f in familles:
                        if f.pk == idfamille:
                            f.certification_date = datetime.datetime.now()
                            f.save()
                            break
                    nbre_coches += 1

        # Message de confirmation
        if nbre_coches == 0:
            messages.add_message(self.request, messages.ERROR, _("Aucune approbation n'a été cochée"))
        elif nbre_coches == 1:
            messages.add_message(self.request, messages.SUCCESS, _("L'approbation cochée a bien été enregistrée"))
        else:
            messages.add_message(self.request, messages.SUCCESS, _("Les %d approbations cochées ont bien été enregistrées") % nbre_coches)
        return HttpResponseRedirect(self.get_success_url())
