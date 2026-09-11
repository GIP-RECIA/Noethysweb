# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from django.db.models import Q
from core.models import PortailMessage, Article, Inscription, Consommation, Lecture
from individus.utils import utils_pieces_manquantes, utils_vaccinations, utils_assurances
from cotisations.utils import utils_cotisations_manquantes
from portail.views.base import CustomView
from portail.utils import utils_approbations
from portail.utils import utils_champs


class Accueil(CustomView, TemplateView):
    template_name = "portail/accueil.html"
    menu_code = "portail_accueil"

    def get_context_data(self, **kwargs):
        context = super(Accueil, self).get_context_data(**kwargs)
        context['page_titre'] = _("Accueil")

        familles = self.get_famille_object()

        if not familles:
            context['nbre_informations_manquantes'] = 0
            context['nbre_pieces_manquantes'] = 0
            context['nbre_messages_non_lus'] = 0
            context['nbre_approbations_requises'] = 0
            context['nbre_vaccinations_manquantes'] = 0
            context['nbre_assurances_manquantes'] = 0
            context['articles'] = []
            context['articles_popups'] = []
            return context

        # Informations manquantes
        context['nbre_informations_manquantes'] = sum(
            utils_champs.Get_renseignements_manquants(famille=f)["NBRE"] for f in familles
        )

        # Pièces manquantes
        context['nbre_pieces_manquantes'] = sum(
            len(utils_pieces_manquantes.Get_pieces_manquantes(famille=f, only_invalides=True, exclure_individus=f.individus_masques.all()))
            for f in familles
        )

        # Messages non lus
        context['nbre_messages_non_lus'] = PortailMessage.objects.filter(
            famille__in=familles, utilisateur__isnull=False, date_lecture__isnull=True
        ).count()

        # Approbations
        context['nbre_approbations_requises'] = sum(
            utils_approbations.Get_approbations_requises(famille=f)["nbre_total"] for f in familles
        )

        # Inscriptions de toutes les familles
        conditions = Q(famille__in=familles) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
        inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions)
        activites = list({inscription.activite: True for inscription in inscriptions}.keys())

        # Vaccins manquants
        context["nbre_vaccinations_manquantes"] = sum([
            len(liste_vaccinations)
            for (f, individu), liste_vaccinations in utils_vaccinations.Get_vaccins_obligatoires_by_inscriptions(inscriptions=inscriptions).items()
        ])

        # Assurances manquantes
        context["nbre_assurances_manquantes"] = sum(
            len(utils_assurances.Get_assurances_manquantes_by_inscriptions(famille=f, inscriptions=inscriptions.filter(famille=f)))
            for f in familles
        )

        # Adhésions manquantes
        if context["parametres_portail"].get("cotisations_afficher_page", False):
            cotisations_manquantes = []
            for f in familles:
                cotisations_manquantes += utils_cotisations_manquantes.Get_cotisations_manquantes(famille=f, exclure_individus=f.individus_masques.all())
            context["cotisations_manquantes"] = cotisations_manquantes

        # Articles (basés sur les activités de toutes les familles)
        conditions = Q(statut="publie") & Q(date_debut__lte=datetime.datetime.now()) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.datetime.now()))
        conditions &= (Q(public__in=("toutes", "presents", "presents_groupes")) | (Q(public="inscrits") & Q(activites__in=activites)))
        articles = Article.objects.select_related("image_article", "album", "sondage", "auteur").filter(conditions).distinct().order_by("-date_debut")
        selection_articles = []
        popups = []
        for article in articles:
            if article.public in ("presents", "presents_groupes"):
                valide = False
                for f in familles:
                    cond = Q(inscription__famille=f, date__gte=article.present_debut, date__lte=article.present_fin, etat__in=("reservation", "present"))
                    if article.public == "presents":
                        cond &= Q(activite__in=article.activites.all())
                    if article.public == "presents_groupes":
                        cond &= Q(groupe__in=article.groupes.all())
                    if Consommation.objects.filter(cond).exists():
                        valide = True
                        break
            else:
                valide = True
            if valide:
                selection_articles.append(article)
                if article.texte_popup:
                    popups.append(article)
        context['articles'] = selection_articles

        # Popups (on utilise la famille principale pour éviter les doublons)
        famille_principale = familles[0]
        context['articles_popups'] = []
        if popups:
            popups_lus = [lecture.article for lecture in Lecture.objects.filter(article__in=popups, famille=famille_principale)]
            for popup in popups:
                if popup not in popups_lus:
                    context['articles_popups'].append(popup)
                    Lecture.objects.create(famille=famille_principale, article=popup)

        return context
