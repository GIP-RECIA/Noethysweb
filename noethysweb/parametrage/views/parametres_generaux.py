#  Copyright (c) 2024 GIP RECIA.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy
from django.core.cache import cache
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from core.views.base import CustomView
from parametrage.forms.parametres_generaux import Formulaire
import django.contrib.messages
from core.models import PortailParametre


class Modifier(CustomView, TemplateView):
    template_name = "core/crud/edit.html"
    compatible_demo = False

    def get_context_data(self, **kwargs):
        context = super(Modifier, self).get_context_data(**kwargs)
        context['page_titre'] = "Paramètres Généraux"
        context['box_titre'] = "Paramètres"
        context['box_introduction'] = "Ajustez les paramètres de Portail utilisateur et cliquez sur le bouton Enregistrer."
        context['form'] = Formulaire()
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # Enregistrement
        dict_parametres = {parametre.code: parametre for parametre in PortailParametre.objects.all()}
        liste_modifications = []
        
        # Traiter le type de compte (radio buttons) et le convertir en deux valeurs booléennes
        type_compte = form.cleaned_data.pop("type_compte", "individu")
        compte_individu = (type_compte == "individu")
        compte_famille = (type_compte == "famille")
        
        # Ajouter les paramètres de compte dans les données à traiter
        form.cleaned_data["compte_individu"] = compte_individu
        form.cleaned_data["compte_famille"] = compte_famille
        
        # Enregistrer tous les paramètres
        for code, valeur in form.cleaned_data.items():
            if code in dict_parametres:
                dict_parametres[code].valeur = str(valeur)
                liste_modifications.append(dict_parametres[code])
            else:
                PortailParametre.objects.create(code=code, valeur=str(valeur))
        if liste_modifications:
            PortailParametre.objects.bulk_update(liste_modifications, ["valeur"])

        # Stocker les états des comptes dans la session
        request.session['compte_individu_active'] = compte_individu
        request.session['compte_famille_active'] = compte_famille
        cache.delete("parametres_portail")

        django.contrib.messages.success(request, 'Paramètres enregistrés')
        return HttpResponseRedirect(reverse_lazy("parametres_generaux"))