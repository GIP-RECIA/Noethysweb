# -*- coding: utf-8 -*-

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.views.base import CustomView
from core.models import Individu
from core.utils.utils_ent import get_user
from fiche_individu.views.individu_ent import CHAMPS_SYNC, Get_lignes_comparaison


class ListeSynchro(CustomView, TemplateView):
    menu_code = "famille_liste"
    template_name = "fiche_famille/famille_ent_synchro.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = "Synchronisation ENT"
        context['box_titre'] = "Synchronisation en masse"
        context['box_introduction'] = "Dépliez un individu pour voir le détail des champs, cochez ceux à synchroniser avec l'ENT, puis cliquez sur Synchroniser."

        individus = Individu.objects.exclude(ent_id=None).exclude(ent_id="").order_by("nom", "prenom")

        lignes = []
        for individu in individus:
            data_ent = get_user(individu.ent_id)
            if not data_ent:
                lignes.append({"individu": individu, "erreur": True, "nb_diff": 0, "champs": []})
                continue

            champs = Get_lignes_comparaison(individu, data_ent)
            nb_diff = len([c for c in champs if c["different"] and c["val_ent"]])

            lignes.append({"individu": individu, "erreur": False, "nb_diff": nb_diff, "champs": champs})

        context['lignes'] = lignes
        return context

    def post(self, request, *args, **kwargs):
        individus = Individu.objects.exclude(ent_id=None).exclude(ent_id="")

        nb_individus_maj = 0
        nb_champs_maj = 0

        for individu in individus:
            champs_selectionnes = request.POST.getlist(f"champs_{individu.pk}")
            if not champs_selectionnes:
                continue

            data_ent = get_user(individu.ent_id)
            if not data_ent:
                continue

            modifie = False
            for champ in CHAMPS_SYNC:
                if champ["code"] in champs_selectionnes:
                    val_ent = data_ent.get(champ["ent_key"]) or ""
                    setattr(individu, champ["code"], val_ent or None)
                    nb_champs_maj += 1
                    modifie = True

            if modifie:
                individu.save()
                nb_individus_maj += 1

        if nb_champs_maj:
            messages.success(request, f"{nb_individus_maj} individu(s) synchronisé(s), {nb_champs_maj} champ(s) mis à jour.")
        else:
            messages.info(request, "Aucun champ sélectionné.")

        return redirect(reverse('ent_synchro_masse'))
