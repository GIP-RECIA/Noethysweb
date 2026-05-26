# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, json
logger = logging.getLogger(__name__)
from django.urls import reverse_lazy
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from django.utils.html import escape
from core.views import crud
from core.models import PortailMessage, PortailRenseignement, Rattachement, Famille, Individu
from portail.forms.transmettre_piece import Formulaire
from portail.views.base import CustomView


def Get_individus_by_famille(request):
    """Retourne une liste d'<option> HTML pour alimenter le select #id_individu (AJAX)."""
    famille_id = request.POST.get("famille")
    if not famille_id or famille_id in ("None", "null", ""):
        return HttpResponse("")

    try:
        famille_id = int(famille_id)
    except (TypeError, ValueError):
        return HttpResponse("", status=400)

    try:
        famille = Famille.objects.get(pk=famille_id)
    except Famille.DoesNotExist:
        return HttpResponse("", status=404)

    user = request.user
    is_allowed = False
    if hasattr(user, "famille") and user.famille and user.famille.pk == famille.pk:
        is_allowed = True
    elif hasattr(user, "individu") and user.individu:
        is_allowed = Rattachement.objects.filter(individu=user.individu, famille=famille, titulaire=1).exists()

    if not is_allowed:
        return HttpResponse("", status=403)

    individus = Individu.objects.filter(rattachement__famille=famille).distinct()
    if hasattr(famille, "individus_masques"):
        individus = individus.exclude(pk__in=famille.individus_masques.all())

    options_html = "".join(
        f'<option value="{individu.pk}">{escape(individu.Get_nom())}</option>'
        for individu in individus
    )
    return HttpResponse(options_html)


def Get_pieces_by_famille(request):
    """Retourne une liste d'<option> HTML pour alimenter le select #id_selection_piece (AJAX)."""
    from individus.utils import utils_pieces_manquantes

    famille_id = request.POST.get("famille")
    if not famille_id or famille_id in ("None", "null", ""):
        options_html = '<option value="9999">Un autre type de pièce</option>'
        return HttpResponse(options_html)

    try:
        famille_id = int(famille_id)
    except (TypeError, ValueError):
        return HttpResponse("", status=400)

    try:
        famille = Famille.objects.get(pk=famille_id)
    except Famille.DoesNotExist:
        return HttpResponse("", status=404)

    user = request.user
    is_allowed = False
    if hasattr(user, "famille") and user.famille and user.famille.pk == famille.pk:
        is_allowed = True
    elif hasattr(user, "individu") and user.individu:
        is_allowed = Rattachement.objects.filter(individu=user.individu, famille=famille, titulaire=1).exists()

    if not is_allowed:
        return HttpResponse("", status=403)

    liste_pieces = utils_pieces_manquantes.Get_pieces_manquantes(
        famille=famille,
        exclure_individus=famille.individus_masques.all(),
    )
    options_html = "".join(
        f'<option value="{index}">{escape(piece["label"])}</option>'
        for index, piece in enumerate(liste_pieces)
    )
    options_html += '<option value="9999">Un autre type de pièce</option>'
    return HttpResponse(options_html)


class Page(CustomView):
    model = PortailMessage
    menu_code = "portail_documents"


    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['page_titre'] = _("Transmettre un document")
        context['box_titre'] = None
        context['box_introduction'] = _("Renseignez les caractéristiques du document et cliquez sur le bouton Envoyer.")
        return context

    def get_success_url(self):
        return reverse_lazy("portail_documents")


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    texte_confirmation = _("Le document a bien été transmis")
    titre_historique = _("Ajouter une pièce")
    template_name = "portail/edit.html"

    def Get_detail_historique(self, instance):
        return "Famille=%s, Pièce=%s" % (instance.famille, instance.Get_nom())

    def Apres_form_valid(self, form=None, instance=None):
        famille = instance.famille or self.get_famille()

        # Mémorisation du renseignement
        PortailRenseignement.objects.create(famille=famille, individu=instance.individu,
                                            categorie="famille_pieces", code="Nouvelle pièce", validation_auto=True,
                                            nouvelle_valeur=json.dumps(instance.Get_nom(), cls=DjangoJSONEncoder), idobjet=instance.pk)
