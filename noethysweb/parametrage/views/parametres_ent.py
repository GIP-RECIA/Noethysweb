from django.views.generic import FormView
from django.shortcuts import render
from django.contrib import messages
from django.urls import reverse_lazy
from django import forms
from django.views.generic import TemplateView
from core.views.base import CustomView
from django.shortcuts import redirect
from parametrage.forms.parameters_ent import Formulaire
from django.http import HttpResponseRedirect
import django.contrib.messages


class Modifier(CustomView, TemplateView):
    template_name = "core/crud/edit.html"
    compatible_demo = False

    def get_context_data(self, **kwargs):
        context = super(Modifier, self).get_context_data(**kwargs)
        context['page_titre'] = "Paramètres ENT"
        context['box_titre'] = "Paramètres"
        context['box_introduction'] = "Ajustez les paramètres de ENT pour  utiliser les données récupérés de l'ENT."
        context['form'] = Formulaire()
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            django.contrib.messages.error(request, 'Aucun paramétre coché!')
            return self.render_to_response(self.get_context_data(form=form))

        # Enregistrement
        # dict_parametres = {parametre.code: parametre for parametre in PortailParametre.objects.all()}
        # liste_modifications = []
        # for code, valeur in form.cleaned_data.items():
        #     if code in dict_parametres:
        #         dict_parametres[code].valeur = str(valeur)
        #         liste_modifications.append(dict_parametres[code])
        #     else:
        #         PortailParametre.objects.create(code=code, valeur=str(valeur))
        # if liste_modifications:
        #     PortailParametre.objects.bulk_update(liste_modifications, ["valeur"])

        # # Stocker les états des cases à cocher dans la session
        # request.session['compte_individu_active'] = form.cleaned_data.get("compte_individu", False)
        # request.session['compte_famille_active'] = form.cleaned_data.get("compte_famille", False)
        # cache.delete("parametres_portail")

        django.contrib.messages.success(request, 'Paramètres enregistrés')
        return HttpResponseRedirect(reverse_lazy("parametres_ent"))
        """
        Traite les erreurs du formulaire
        """
        messages.error(self.request, 'Veuillez corriger les erreurs ci-dessous.')
        return super().form_invalid(form)