# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime, decimal
logger = logging.getLogger(__name__)
from django.db.models import Q
from django.views.generic import TemplateView
from django.utils.translation import gettext as _
from core.models import Inscription, PortailPeriode, Rattachement
from individus.utils import utils_familles
from portail.views.base import CustomView
from portail.utils import utils_approbations


class Page(CustomView, TemplateView):

    def get_famille_object(self):
        """Retourne la/les familles rattachées à l'utilisateur."""
        user = self.request.user
        if hasattr(user, "famille") and user.famille:
            return [user.famille]
        if hasattr(user, "individu") and user.individu:
            rattachements = Rattachement.objects.select_related("famille").filter(individu=user.individu, titulaire=1)
            familles = []
            seen_ids = set()
            for rattachement in rattachements:
                if rattachement.famille and rattachement.famille_id not in seen_ids:
                    familles.append(rattachement.famille)
                    seen_ids.add(rattachement.famille_id)
            return familles
        return []


class View(Page):
    menu_code = "portail_reservations"
    template_name = "portail/reservations.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = _("Réservations")

        familles = self.get_famille_object()
        context["familles"] = familles

        # -----------------------------
        # Données par famille (multi-famille)
        # -----------------------------
        donnees_par_famille = []
        blocage_impayes_param = context["parametres_portail"].get("reservations_blocage_impayes", None)
        for famille in familles:
            # Vérifie que la famille est autorisée à faire des réservations
            if not getattr(famille, "internet_reservations", False):
                donnees_par_famille.append({
                    "famille": famille,
                    "reservations": [],
                    "dict_periodes": {},
                    "nbre_approbations_requises": 0,
                    "blocage_impayes": False,
                })
                continue

            # Importation des inscriptions
            conditions = Q(famille=famille) & Q(statut="ok") & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
            conditions &= Q(activite__portail_reservations_affichage="TOUJOURS") & (Q(activite__date_fin__isnull=True) | Q(activite__date_fin__gte=datetime.date.today()))
            conditions &= Q(internet_reservations=True) & Q(individu__deces=False)
            inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions).exclude(individu__in=famille.individus_masques.all())

            # Récupération des individus
            liste_individus = sorted(list({inscription.individu for inscription in inscriptions}), key=lambda individu: individu.prenom)

            # Récupération des activités pour chaque individu
            dict_activites_par_individu = {}
            liste_activites = []
            for inscription in inscriptions:
                dict_activites_par_individu.setdefault(inscription.individu, [])
                if inscription.activite not in dict_activites_par_individu[inscription.individu]:
                    dict_activites_par_individu[inscription.individu].append(inscription.activite)
                if inscription.activite not in liste_activites:
                    liste_activites.append(inscription.activite)

            reservations_par_individu = []
            for individu in liste_individus:
                reservations_par_individu.append({
                    "individu": individu,
                    "activites": sorted(dict_activites_par_individu.get(individu, []), key=lambda activite: activite.nom),
                })

            # Récupération des périodes de réservation
            conditions = Q(activite__in=liste_activites)
            conditions &= (Q(affichage="TOUJOURS") | (Q(affichage="PERIODE") & Q(affichage_date_debut__lte=datetime.datetime.now()) & Q(affichage_date_fin__gte=datetime.datetime.now())))
            periodes = PortailPeriode.objects.select_related("activite").prefetch_related("categories").filter(conditions).order_by("date_debut")
            dict_periodes = {}
            for periode in periodes:
                if periode.Is_famille_authorized(famille=famille):
                    dict_periodes.setdefault(periode.activite, [])
                    dict_periodes[periode.activite].append(periode)

            # Approbations
            approbations_requises = utils_approbations.Get_approbations_requises(famille=famille)

            # Blocage si impayés
            blocage_impayes = False
            if blocage_impayes_param and not famille.blocage_impayes_off:
                blocage_impayes_decimal = decimal.Decimal(blocage_impayes_param)
                factures = False
                if blocage_impayes_decimal > decimal.Decimal(10000):
                    blocage_impayes_decimal -= decimal.Decimal(10000)
                    factures = True
                if utils_familles.Get_solde_famille(idfamille=famille.pk, date_situation=datetime.date.today(), factures=factures) >= blocage_impayes_decimal:
                    blocage_impayes = True

            donnees_par_famille.append({
                "famille": famille,
                "reservations": reservations_par_individu,
                "dict_periodes": dict_periodes,
                "nbre_approbations_requises": approbations_requises["nbre_total"],
                "blocage_impayes": blocage_impayes,
            })

        context["donnees_par_famille"] = donnees_par_famille

        # -----------------------------
        # Contexte historique (template actuel)
        # -----------------------------
        famille_principale = familles[0] if familles else None

        # Si pas de famille, pas de réservations possibles
        if not famille_principale:
            context['liste_individus'] = []
            context['dict_periodes'] = {}
            context['nbre_approbations_requises'] = 0
            context['blocage_impayes'] = False
            return context

        # Vérifie que la famille est autorisée à faire des réservations
        if not famille_principale.internet_reservations:
            context['liste_individus'] = []
            return context

        # Importation des inscriptions
        conditions = Q(famille=famille_principale) & Q(statut="ok") & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
        conditions &= Q(activite__portail_reservations_affichage="TOUJOURS") & (Q(activite__date_fin__isnull=True) | Q(activite__date_fin__gte=datetime.date.today()))
        conditions &= Q(internet_reservations=True) & Q(individu__deces=False)
        inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions).exclude(individu__in=famille_principale.individus_masques.all())

        # Récupération des individus
        context['liste_individus'] = sorted(list(set([inscription.individu for inscription in inscriptions])), key=lambda individu: individu.prenom)

        # Récupération des activités pour chaque individu
        dict_inscriptions = {}
        liste_activites = []
        for inscription in inscriptions:
            dict_inscriptions.setdefault(inscription.individu, [])
            if inscription.activite not in dict_inscriptions[inscription.individu]:
                dict_inscriptions[inscription.individu].append(inscription.activite)
            if inscription.activite not in liste_activites:
                liste_activites.append(inscription.activite)
        for individu in context['liste_individus']:
            individu.activites = sorted(dict_inscriptions[individu], key=lambda activite: activite.nom)

        # Récupération des périodes de réservation
        conditions = Q(activite__in=liste_activites)
        conditions &= (Q(affichage="TOUJOURS") | (Q(affichage="PERIODE") & Q(affichage_date_debut__lte=datetime.datetime.now()) & Q(affichage_date_fin__gte=datetime.datetime.now())))
        periodes = PortailPeriode.objects.select_related("activite").prefetch_related("categories").filter(conditions).order_by("date_debut")
        dict_periodes = {}
        for periode in periodes:
            if periode.Is_famille_authorized(famille=famille_principale):
                dict_periodes.setdefault(periode.activite, [])
                dict_periodes[periode.activite].append(periode)
        context['dict_periodes'] = dict_periodes

        # Approbations
        approbations_requises = utils_approbations.Get_approbations_requises(famille=famille_principale)
        context['nbre_approbations_requises'] = approbations_requises["nbre_total"]

        # Blocage si impayés
        blocage_impayes = context["parametres_portail"].get("reservations_blocage_impayes", None)
        context["blocage_impayes"] = False

        if blocage_impayes and not famille_principale.blocage_impayes_off:
            blocage_impayes = decimal.Decimal(blocage_impayes)
            factures = False
            if blocage_impayes > decimal.Decimal(10000):
                blocage_impayes -= decimal.Decimal(10000)
                factures = True
            if utils_familles.Get_solde_famille(idfamille=famille_principale.pk, date_situation=datetime.date.today(), factures=factures) >= blocage_impayes:
                context["blocage_impayes"] = True

        return context
