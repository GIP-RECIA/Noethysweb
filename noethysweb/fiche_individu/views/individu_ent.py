# -*- coding: utf-8 -*-

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.db import transaction
from core.models import Individu
from core.views.base import CustomView
from core.utils.utils_ent import get_user
from fiche_individu.views.individu import Onglet


CHAMPS_SYNC = [
    {"code": "nom",        "label": "Nom",              "ent_key": "lastName"},
    {"code": "prenom",     "label": "Prénom",           "ent_key": "firstName"},
    {"code": "mail",       "label": "Email",            "ent_key": "email"},
    {"code": "tel_mobile", "label": "Téléphone mobile", "ent_key": "mobile"},
    {"code": "rue_resid",  "label": "Adresse",          "ent_key": "address"},
    {"code": "cp_resid",   "label": "Code postal",      "ent_key": "zipCode"},
    {"code": "ville_resid","label": "Ville",            "ent_key": "city"},
]


def Get_lignes_comparaison(individu, data_ent):
    """ Retourne la liste des champs comparés entre Noethysweb et l'ENT pour un individu. """
    lignes = []
    for champ in CHAMPS_SYNC:
        val_noethys = getattr(individu, champ["code"]) or ""
        val_ent = data_ent.get(champ["ent_key"]) or ""
        lignes.append({
            "code": champ["code"],
            "label": champ["label"],
            "val_noethys": val_noethys,
            "val_ent": val_ent,
            "different": str(val_noethys).strip() != str(val_ent).strip(),
        })
    return lignes


class SynchroniserIndividu(Onglet, TemplateView):
    menu_code = "individus_toc"
    template_name = "fiche_individu/individu_ent_synchro.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box_titre'] = "Synchronisation ENT"
        context['onglet_actif'] = "resume"

        individu = context['individu']

        if not individu.ent_id:
            context['erreur'] = "Cet individu n'a pas été importé depuis l'ENT."
            return context

        data_ent = get_user(individu.ent_id)
        if not data_ent:
            context['erreur'] = "Impossible de récupérer les données depuis l'ENT. Vérifiez la connexion."
            return context

        context['lignes'] = Get_lignes_comparaison(individu, data_ent)
        return context

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        idfamille = self.kwargs['idfamille']
        idindividu = self.kwargs['idindividu']
        individu = Individu.objects.get(pk=idindividu)

        data_ent = get_user(individu.ent_id)
        if not data_ent:
            messages.error(request, "Impossible de récupérer les données ENT.")
            return redirect(reverse('individu_ent_synchro', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))

        champs_selectionnes = request.POST.getlist('champs')
        nb_modifs = 0

        for champ in CHAMPS_SYNC:
            if champ["code"] in champs_selectionnes:
                val_ent = data_ent.get(champ["ent_key"]) or ""
                setattr(individu, champ["code"], val_ent or None)
                nb_modifs += 1

        if nb_modifs:
            individu.save()
            messages.success(request, f"{nb_modifs} champ(s) synchronisé(s) depuis l'ENT.")
        else:
            messages.info(request, "Aucun champ sélectionné.")

        return redirect(reverse('individu_ent_synchro', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))
