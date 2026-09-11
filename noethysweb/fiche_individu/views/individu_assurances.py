# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json
from django.urls import reverse_lazy, reverse
from django.db.models import Q
from django.http import JsonResponse, HttpResponseRedirect
from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import get_object_or_404
from core.views.base import CustomView
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Assurance, Famille, Rattachement
from core.utils import utils_historique
from fiche_individu.forms.individu_assurances import Formulaire
from fiche_individu.views.individu import Onglet
from fiche_individu.forms.assureurs import Formulaire as Formulaire_assureur
from fiche_individu.forms.individu_assurances_importer import Formulaire as Formulaire_importer


def Ajouter_assureur(request):
    """ Ajouter un assureur dans la liste de choix """
    valeurs = json.loads(request.POST.get("valeurs"))

    # Formatage des champs
    valeurs["nom"] = valeurs["nom"].upper()
    valeurs["rue_resid"] = valeurs["rue_resid"].title()
    valeurs["ville_resid"] = valeurs["ville_resid"].upper()

    # Vérification des données saisies
    form = Formulaire_assureur(valeurs)
    if not form.is_valid():
        messages_erreurs = ["%s : %s" % (field.title(), erreur[0].message) for field, erreur in form.errors.as_data().items()]
        return JsonResponse({"erreur": ", ".join(messages_erreurs)}, status=401)

    # Sauvegarde de l'assureur
    instance = form.save()
    return JsonResponse({"id": instance.pk, "nom": instance.Get_nom(afficher_ville=True)})


class Page(Onglet):
    model = Assurance
    url_liste = "individu_assurances_liste"
    url_ajouter = "individu_assurances_ajouter"
    url_modifier = "individu_assurances_modifier"
    url_supprimer = "individu_assurances_supprimer"
    description_liste = "Consultez et saisissez ici les assurances de l'individu."
    description_saisie = "Saisissez toutes les informations concernant l'assurance et cliquez sur le bouton Enregistrer."
    objet_singulier = "une assurance"
    objet_pluriel = "des assurances"

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)
        if not hasattr(self, "verbe_action"):
            context['box_titre'] = "Assurances"
        context['onglet_actif'] = "assurances"
        if self.request.user.has_perm("core.individu_assurances_modifier"):
            context['boutons_liste'] = [
                {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(self.url_ajouter, kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)}), "icone": "fa fa-plus"},
                {"label": "Importer depuis une autre fiche", "classe": "btn btn-default", "href": reverse_lazy("individu_assurances_importer", kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)}), "icone": "fa fa-download"}, ]
        context['form_ajout'] = Formulaire_assureur()
        return context

    def test_func_page(self):
        if getattr(self, "verbe_action", None) in ("Ajouter", "Modifier", "Supprimer") and not self.request.user.has_perm("core.individu_assurances_modifier"):
            return False
        return True

    def get_form_kwargs(self, **kwargs):
        """ Envoie l'idindividu au formulaire """
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["idindividu"] = self.Get_idindividu()
        form_kwargs["idfamille"] = self.Get_idfamille()
        return form_kwargs

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        url = self.url_liste
        if "SaveAndNew" in self.request.POST:
            url = self.url_ajouter
        return reverse_lazy(url, kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)})



class Liste(Page, crud.Liste):
    model = Assurance
    template_name = "fiche_individu/individu_liste.html"

    def get_queryset(self):
        return Assurance.objects.select_related("assureur").filter(Q(individu=self.Get_idindividu()) & Q(famille=self.Get_idfamille()) & self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        return context

    class datatable_class(MyDatatable):
        filtres = ["idassurance", "assureur__nom", "num_contrat", "date_debut", "date_fin"]
        num_contrat = columns.TextColumn("N° de contrat", processor="Get_num_contrat")
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idassurance", "assureur", "num_contrat", "date_debut", "date_fin"]
            ordering = ["date_debut"]
            processors = {
                'date_debut': helpers.format_date('%d/%m/%Y'),
                'date_fin': helpers.format_date('%d/%m/%Y'),
            }

        def Get_num_contrat(self, instance, *args, **kwargs):
            return instance.num_contrat

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            view = kwargs["view"]
            if not view.request.user.has_perm("core.individu_assurances_modifier"):
                return "<span class='text-red' title='Accès interdit'><i class='fa fa-lock'></i></span>"
            kwargs = view.kwargs
            kwargs["pk"] = instance.pk
            html = [
                self.Create_bouton_modifier(url=reverse(view.url_modifier, kwargs=kwargs)),
                self.Create_bouton_supprimer(url=reverse(view.url_supprimer, kwargs=kwargs)),
            ]
            # Réattribution manuelle : uniquement si l'individu est rattaché à plusieurs
            # familles (ex: enfant partagé après une séparation) - même règle que pour les
            # prestations (ReattribuerPrestation).
            if instance.individu_id:
                nb_familles = Rattachement.objects.filter(individu_id=instance.individu_id).values("famille_id").distinct().count()
                if nb_familles > 1:
                    html.append(self.Create_bouton(
                        url=reverse("individu_assurances_reattribuer", kwargs=kwargs),
                        title="Réattribuer à une autre famille", icone="fa-exchange"
                    ))
            return self.Create_boutons_actions(html)



class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    template_name = "fiche_individu/individu_assurances.html"

class Modifier(Page, crud.Modifier):
    form_class = Formulaire
    template_name = "fiche_individu/individu_assurances.html"

class Supprimer(Page, crud.Supprimer):
    template_name = "fiche_individu/individu_delete.html"


class Importer(Page, TemplateView):
    form_class = Formulaire_importer
    template_name = "fiche_individu/individu_edit.html"
    mode = "fiche_individu"

    def get_context_data(self, **kwargs):
        context = super(Importer, self).get_context_data(**kwargs)
        context['box_introduction'] = "Cochez la ou les assurances à importer et cliquez sur le bouton Importer."
        context['form'] = Formulaire_importer(idfamille=self.kwargs['idfamille'], idindividu=self.kwargs['idindividu'], request=self.request)
        return context

    def post(self, request, **kwargs):
        # Validation du form
        form = Formulaire_importer(request.POST, idfamille=self.kwargs['idfamille'], idindividu=self.kwargs['idindividu'], request=self.request)
        if form.is_valid() == False:
            return self.render_to_response(self.get_context_data(form=form))

        # Importation des assurances
        liste_txt = form.cleaned_data.get("assurances", "")
        if liste_txt:
            liste_idassurance = liste_txt.split(";")
            for assurance in Assurance.objects.filter(pk__in=[int(idassurance) for idassurance in liste_idassurance]):
                assurance.pk = None
                assurance.individu_id = self.kwargs['idindividu']
                assurance.save()

        return HttpResponseRedirect(reverse_lazy("individu_assurances_liste", args=(self.kwargs['idfamille'], self.kwargs['idindividu'])))


class ReattribuerAssurance(CustomView, TemplateView):
    """
    Corrige manuellement une assurance restée ambiguë après une séparation de famille (enfant
    partagé, aucun titulaire clair pour trancher automatiquement) - même outil que pour les
    prestations (ReattribuerPrestation), appliqué ici à l'assurance.
    """
    template_name = "fiche_individu/individu_assurances_reattribuer.html"
    menu_code = "individus_toc"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assurance = get_object_or_404(Assurance, pk=self.kwargs["pk"])

        context["page_titre"] = "Réattribuer une assurance"
        context["box_titre"] = "Réattribution manuelle"
        context["box_introduction"] = "Sélectionnez la famille à laquelle vous souhaitez réattribuer cette assurance."
        context["idfamille"] = self.kwargs["idfamille"]
        context["idindividu"] = self.kwargs["idindividu"]
        context["assurance"] = assurance
        context["familles"] = Famille.objects.filter(rattachement__individu_id=assurance.individu_id).distinct()
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        assurance = get_object_or_404(Assurance, pk=self.kwargs["pk"])
        idfamille_cible = request.POST.get("idfamille_cible")

        if not idfamille_cible:
            messages.error(request, "Veuillez sélectionner une famille.")
            return HttpResponseRedirect(reverse("individu_assurances_reattribuer", kwargs=self.kwargs))

        famille_cible = get_object_or_404(Famille, pk=idfamille_cible)

        # Vérifie que l'individu est bien rattaché à cette famille cible (sécurité) - même
        # garde-fou que pour les prestations.
        if not Rattachement.objects.filter(individu_id=assurance.individu_id, famille=famille_cible).exists():
            messages.error(request, "Cette famille n'est pas autorisée pour cette assurance.")
            return HttpResponseRedirect(reverse("individu_assurances_reattribuer", kwargs=self.kwargs))

        famille_origine = assurance.famille
        assurance.famille = famille_cible
        assurance.save()


        # Traçabilité (même principe que pour les liaisons ENT et la réattribution de
        # prestation) : pouvoir remonter à l'agent qui a déplacé cette donnée entre 2 familles.
        utils_historique.Ajouter(
            titre="Réattribution manuelle d'une assurance",
            detail=f"Assurance « {assurance.assureur} » (contrat {assurance.num_contrat}) déplacée de « {famille_origine.nom if famille_origine else '?'} » vers « {famille_cible.nom} ».",
            utilisateur=request.user, famille=famille_cible.pk, individu=assurance.individu_id,
        )

        messages.success(request, f"L'assurance a été réattribuée à la famille {famille_cible.nom}.")
        return HttpResponseRedirect(reverse("individu_assurances_liste", kwargs={"idfamille": famille_cible.pk, "idindividu": self.kwargs["idindividu"]}))
