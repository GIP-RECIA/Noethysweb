# -*- coding: utf-8 -*-

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from core.views.base import CustomView
from core.models import Individu, Rattachement
from core.utils.utils_ent import ent_est_actif

CHOIX_ENFANT = [(4, "Garçon"), (5, "Fille")]
CHOIX_ADULTE = [(1, "Monsieur"), (2, "Mademoiselle"), (3, "Madame")]


class ListeCivilitesAVerifier(CustomView, TemplateView):
    menu_code = "famille_liste"
    template_name = "fiche_famille/civilites_a_verifier.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Civilités à vérifier"
        context["box_titre"] = "Civilités à vérifier"
        context["box_introduction"] = "Confirmez ou corrigez la civilité des individus importés depuis l'ENT (leur civilité réelle n'est pas fournie par l'ENT)."

        individus = Individu.objects.filter(civilite_a_verifier=True).order_by("nom", "prenom")
        rattachements = Rattachement.objects.filter(individu__in=individus).select_related("famille")
        ids_enfants = {r.individu_id for r in rattachements if r.categorie == 2}

        # Regroupe les individus par famille (un individu peut avoir plusieurs rattachements,
        # on prend le premier trouvé comme famille de référence pour l'affichage)
        famille_par_individu = {}
        for r in rattachements:
            famille_par_individu.setdefault(r.individu_id, r.famille)

        groupes = {}
        for individu in individus:
            famille = famille_par_individu.get(individu.pk)
            cle = famille.pk if famille else 0
            if cle not in groupes:
                groupes[cle] = {"famille": famille, "lignes": []}
            groupes[cle]["lignes"].append({
                "individu": individu,
                "choix": CHOIX_ENFANT if individu.pk in ids_enfants else CHOIX_ADULTE,
            })

        context["groupes"] = sorted(groupes.values(), key=lambda g: g["famille"].nom if g["famille"] else "")
        context["nb_a_verifier"] = individus.count()
        return context

    def get(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return redirect(reverse("famille_liste"))
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        if not ent_est_actif():
            messages.error(request, "L'intégration ENT est désactivée.")
            return redirect(reverse("famille_liste"))

        ids_confirmes = request.POST.getlist("individus_confirmes")
        nb_confirmes = 0

        # Rejoue le même calcul que get_context_data pour savoir qui est un enfant - jamais
        # confiance dans ce que l'écran a affiché : sans ça, une requête modifiée à la main
        # (ou un futur bug côté template) pourrait attribuer une civilité d'adulte à un
        # enfant, et recréer exactement le problème que cet écran sert à corriger.
        ids_enfants = set(
            Rattachement.objects.filter(individu_id__in=ids_confirmes, categorie=2).values_list("individu_id", flat=True)
        )

        for individu_id in ids_confirmes:
            civilite_brute = request.POST.get(f"civilite_{individu_id}")
            if not civilite_brute:
                continue
            try:
                civilite = int(civilite_brute)
            except ValueError:
                continue

            choix_valides = CHOIX_ENFANT if int(individu_id) in ids_enfants else CHOIX_ADULTE
            if civilite not in dict(choix_valides):
                continue

            individu = Individu.objects.filter(pk=individu_id, civilite_a_verifier=True).first()
            if individu:
                individu.civilite = civilite
                individu.civilite_a_verifier = False
                individu.save()
                nb_confirmes += 1

        if nb_confirmes:
            messages.success(request, f"{nb_confirmes} civilité(s) confirmée(s).")
        else:
            messages.info(request, "Aucun individu sélectionné.")

        return redirect(reverse("civilites_a_verifier"))
