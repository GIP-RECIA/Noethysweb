# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime, json
logger = logging.getLogger(__name__)
from django.db.models import Q
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from core.models import Inscription, PortailRenseignement, Activite, Rattachement
from portail.views.base import CustomView


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
    menu_code = "portail_activites"
    template_name = "portail/activites.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = _("Activités")

        familles = self.get_famille_object()
        context["familles"] = familles

        # -----------------------------
        # Données par famille (multi-famille)
        # -----------------------------
        donnees_par_famille = []
        dict_activites = {activite.pk: activite.nom for activite in Activite.objects.all()}
        for famille in familles:
            # Importation des inscriptions (par famille)
            conditions = Q(famille=famille) & Q(statut="ok") & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today())) & Q(individu__deces=False)
            inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions).exclude(individu__in=famille.individus_masques.all())

            # Récupération des individus
            liste_individus = sorted(list({inscription.individu for inscription in inscriptions}), key=lambda individu: individu.prenom)

            # Récupération des activités pour chaque individu
            dict_inscriptions = {}
            for inscription in inscriptions:
                dict_inscriptions.setdefault(inscription.individu, [])
                dict_inscriptions[inscription.individu].append(inscription)

            activites_par_individu = []
            for individu in liste_individus:
                activites_par_individu.append({
                    "individu": individu,
                    "inscriptions": sorted(dict_inscriptions.get(individu, []), key=lambda inscription: inscription.activite.nom),
                })

            # Demandes d'inscription en attente de traitement (par famille)
            demandes = []
            for demande in PortailRenseignement.objects.select_related("individu").filter(
                famille=famille,
                etat="ATTENTE",
                code="inscrire_activite",
            ).order_by("individu__prenom"):
                demande.nom_activite = dict_activites.get(int(json.loads(demande.nouvelle_valeur).split(";")[0]), "?")
                demandes.append(demande)

            donnees_par_famille.append({
                "famille": famille,
                "activites": activites_par_individu,
                "demandes_inscriptions_attente": demandes,
            })

        context["donnees_par_famille"] = donnees_par_famille

        # -----------------------------
        # Contexte historique (template actuel)
        # -----------------------------
        # Importation des inscriptions (toutes familles confondues)
        conditions = Q(famille__in=familles) & Q(statut="ok") & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today())) & Q(individu__deces=False)
        individus_masques = set()
        for famille in familles:
            individus_masques.update(list(famille.individus_masques.all()))
        inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions).exclude(individu__in=individus_masques)

        # Récupération des individus
        context['liste_individus'] = sorted(list(set([inscription.individu for inscription in inscriptions])), key=lambda individu: individu.prenom)

        # Récupération des activités pour chaque individu
        dict_inscriptions = {}
        for inscription in inscriptions:
            dict_inscriptions.setdefault(inscription.individu, [])
            dict_inscriptions[inscription.individu].append(inscription)
        for individu in context['liste_individus']:
            individu.inscriptions = sorted(dict_inscriptions[individu], key=lambda inscription: inscription.activite.nom)

        # Demandes d'inscription en attente de traitement
        demandes = []
        for demande in PortailRenseignement.objects.select_related("individu").filter(famille__in=familles, etat="ATTENTE", code="inscrire_activite").order_by("individu__prenom"):
            demande.nom_activite = dict_activites.get(int(json.loads(demande.nouvelle_valeur).split(";")[0]), "?")
            demandes.append(demande)
        context["demandes_inscriptions_attente"] = demandes

        # Vérifie si des activités sont ouvertes à l'inscription
        context["activites_ouvertes_inscription"] = Activite.objects.filter((Q(portail_inscriptions_affichage="TOUJOURS") | (Q(portail_inscriptions_affichage="PERIODE") & Q(portail_inscriptions_date_debut__lte=datetime.datetime.now()) & Q(portail_inscriptions_date_fin__gte=datetime.datetime.now())))).exists()

        return context
