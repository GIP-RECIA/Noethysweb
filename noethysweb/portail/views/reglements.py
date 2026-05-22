# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, json, datetime
logger = logging.getLogger(__name__)
from django.http import JsonResponse
from django.views.generic import TemplateView
from django.utils.translation import gettext as _
from core.models import Reglement, ModeleImpression, Recu, Rattachement
from portail.views.base import CustomView


def imprimer_recu(request):
    """ Imprimer un reçu de règlement au format PDF """
    idreglement = int(request.POST.get("idreglement", 0))
    idmodele = int(request.POST.get("idmodele_impression", 0))

    # Importation des options d'impression
    modele_impression = ModeleImpression.objects.get(pk=idmodele)
    dict_options = json.loads(modele_impression.options)
    dict_options["modele"] = modele_impression.modele_document

    # Vérification que le règlement appartient à l'une des familles de l'utilisateur
    if hasattr(request.user, "famille") and request.user.famille:
        famille_ids = [request.user.famille.pk]
    else:
        rattachements = Rattachement.objects.filter(individu=request.user.individu, titulaire=1)
        famille_ids = [r.famille_id for r in rattachements if r.famille_id]
    reglement = Reglement.objects.get(pk=idreglement, famille_id__in=famille_ids)

    # Création du numéro de reçu
    numero = 1
    dernier_recu = Recu.objects.last()
    if dernier_recu:
        numero = dernier_recu.numero + 1

    # Création du PDF
    donnees = {"idreglement": reglement.pk, "date_edition": datetime.date.today(), "numero": numero,
               "idmodele": modele_impression.modele_document_id, "idfamille": reglement.famille_id, "signataire": dict_options["signataire"],
               "intro": dict_options["intro"], "afficher_prestations": dict_options["afficher_prestations"]}

    # Mémorisation du reçu
    Recu.objects.create(numero=numero, famille_id=reglement.famille_id, date_edition=donnees["date_edition"],
                        reglement=reglement, utilisateur=request.user)

    from fiche_famille.views.reglement_recu import Generer_recu
    resultat = Generer_recu(donnees=donnees)
    return JsonResponse(resultat)


class View(CustomView, TemplateView):
    menu_code = "portail_reglements"
    template_name = "portail/reglements.html"

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

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = _("Règlements")
        familles = self.get_famille_object()
        donnees_par_famille = []
        for famille in familles:
            donnees_par_famille.append({
                "famille": famille,
                "liste_reglements": Reglement.objects.select_related("mode", "depot").filter(famille=famille).order_by("-date"),
            })
        context["donnees_par_famille"] = donnees_par_famille
        return context
