# -*- coding: utf-8 -*-

#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from core.views import crud
from core.models import Activite
from parametrage.forms.activites_renseignements import Formulaire
from parametrage.views.activites import Onglet



class Modifier(Onglet, crud.Modifier):
    form_class = Formulaire
    template_name = "parametrage/activite_edit.html"

    def get_context_data(self, **kwargs):
        context = super(Modifier, self).get_context_data(**kwargs)
        context['box_titre'] = "Renseignements"
        context['box_introduction'] = "Sélectionnez les renseignements et pièces qu'un individu inscrit doit fournir."
        context['onglet_actif'] = "renseignements"
        return context

    def get_success_url(self):
        return reverse_lazy("activites_resume", kwargs={'idactivite': self.kwargs['idactivite']})

    def get_object(self):
        return Activite.objects.get(pk=self.kwargs['idactivite'])