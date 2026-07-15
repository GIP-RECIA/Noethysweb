# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.views.base import CustomView
from core.models import Individu
from core.utils.utils_ent import get_user, get_headers
from fiche_individu.views.individu_ent import CHAMPS_SYNC, Get_lignes_comparaison

MAX_WORKERS = 5  # limite le nombre d'appels simultanés vers l'ENT


def _recuperer_donnees_ent(individus):
    """ Récupère les données ENT de plusieurs individus en parallèle. Retourne {individu.pk: data_ent ou None}. """
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        resultats = executor.map(lambda individu: (individu.pk, get_user(individu.ent_id)), individus)
    return dict(resultats)


class ListeSynchro(CustomView, TemplateView):
    menu_code = "famille_liste"
    template_name = "fiche_famille/famille_ent_synchro.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = "Synchronisation ENT"
        context['box_titre'] = "Synchronisation en masse"
        context['box_introduction'] = "Dépliez un individu pour voir le détail des champs, cochez ceux à synchroniser avec l'ENT, puis cliquez sur Synchroniser."

        # Vérifie la connexion avant d'interroger l'ENT : si elle échoue pour tout le monde
        # (identifiants incorrects, ENT désactivé...), chaque individu se retrouverait marqué
        # "Introuvable dans l'ENT" comme s'il avait été supprimé côté ENT, alors que c'est en
        # fait une panne de connexion générale - deux situations très différentes à ne pas confondre.
        context['erreur_connexion'] = get_headers() is None

        lignes = []
        if not context['erreur_connexion']:
            individus = list(Individu.objects.exclude(ent_id=None).exclude(ent_id="").order_by("nom", "prenom"))
            donnees_ent = _recuperer_donnees_ent(individus)

            for individu in individus:
                data_ent = donnees_ent.get(individu.pk)
                if not data_ent:
                    lignes.append({"individu": individu, "erreur": True, "nb_diff": 0, "champs": []})
                    continue

                champs = Get_lignes_comparaison(individu, data_ent)
                nb_diff = len([c for c in champs if c["different"] and c["val_ent"]])

                lignes.append({"individu": individu, "erreur": False, "nb_diff": nb_diff, "champs": champs})

        context['lignes'] = lignes
        return context

    def post(self, request, *args, **kwargs):
        individus = list(Individu.objects.exclude(ent_id=None).exclude(ent_id=""))

        # Ne récupère les données ENT que pour les individus ayant au moins un champ coché
        individus_a_synchroniser = [i for i in individus if request.POST.getlist(f"champs_{i.pk}")]
        donnees_ent = _recuperer_donnees_ent(individus_a_synchroniser)

        nb_individus_maj = 0
        nb_champs_maj = 0

        for individu in individus_a_synchroniser:
            champs_selectionnes = request.POST.getlist(f"champs_{individu.pk}")

            data_ent = donnees_ent.get(individu.pk)
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
