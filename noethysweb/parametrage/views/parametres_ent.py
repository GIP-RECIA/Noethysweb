from django.urls import reverse_lazy
from django.core.cache import cache
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from django.contrib import messages
from core.views.base import CustomView
from core.models import Organisateur
from parametrage.forms.parametres_ent import Formulaire


class Modifier(CustomView, TemplateView):
    template_name = "core/crud/edit.html"
    compatible_demo = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Paramètres ENT"
        context["box_titre"] = "Paramètres ENT"
        context["box_introduction"] = "Saisissez les paramètres de connexion à l'ENT (Espace Numérique de Travail)."
        organisateur = Organisateur.objects.filter(pk=1).first()
        context["form"] = kwargs.get("form") or Formulaire(instance=organisateur)
        return context

    def post(self, request, **kwargs):
        organisateur = Organisateur.objects.filter(pk=1).first()
        form = Formulaire(request.POST, instance=organisateur, request=request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        form.save()
        cache.delete("organisateur") # vide le cache pour que la prochain appel relise la BD
        messages.success(request, "Paramètres ENT enregistrés")
        return HttpResponseRedirect(reverse_lazy("parametrage_toc"))
