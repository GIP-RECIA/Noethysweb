from django.views.generic import TemplateView
from core.views.base import CustomView
from django.db import transaction
from core.models import Ecole, Classe, NiveauScolaire, Secteur
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
import logging
from django.contrib import messages

logger = logging.getLogger(__name__)



class EntEcole(CustomView, TemplateView):
    menu_code = "ecole_recherche_ent"
    template_name = "parametrage/ecole_ent.html"


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['ecole'] = self.request.session.get('ecole_ent', [])
        context['page_titre'] = "L'école trouvé dans l'ENT"
        return context
    
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        search_info = self.request.session.get('ecole_search_info', {})
        secteurs_ids = search_info.get("secteurs", [])
        ecole_id = request.POST.get("ecole_id")
        ecole_ent = self.request.session.get('ecole_ent', [])
        ecole = Ecole.objects.filter(uai=ecole_id).first()
        if ecole:
            messages.add_message(self.request, messages.ERROR, "Ecole existe déjà")
            url_success = reverse_lazy("ecoles_liste", kwargs={})
        else:
            if action == "ajouter_nouvelle_ecole":              
                url_success = reverse_lazy("ecoles_ajouter", kwargs={})
            else:
                ecole = self.ajouter_ecole(ecole_ent, secteurs_ids)
                self.ajouter_niveaux_scolaire(ecole_ent.get("niveaux"))
                self.ajouter_classes(ecole, ecole_ent.get("classes"))
                messages.add_message(self.request, messages.SUCCESS, "Ajout enregistré")
                url_success = reverse_lazy("ecoles_liste", kwargs={})
            
        return HttpResponseRedirect(url_success)
    
    def ajouter_ecole(self, ecole_info, secteurs_ids):
        ecole = Ecole(
                nom = ecole_info.get("nom"),
                rue = ecole_info.get("rue"),
                cp = ecole_info.get("cp"),
                ville = ecole_info.get("ville"),
                tel = ecole_info.get("tel"),
                fax = ecole_info.get("fax"),
                mail = ecole_info.get("mail"),
                uai = ecole_info.get("uai")
                )
        ecole.save()
        if secteurs_ids:
            secteurs_qs = Secteur.objects.filter(idsecteur__in=secteurs_ids)
            ecole.secteurs.set(secteurs_qs)
        ecole.save()
        return ecole

    def ajouter_niveaux_scolaire(self, niveaux_list):
        for niveau in niveaux_list:
            exist_niveau = NiveauScolaire.objects.filter(nom=niveau.get("nom")).first()
            if not exist_niveau:
                nouveau_niveau = NiveauScolaire(
                    ordre = niveau.get("ordre"),
                    nom = niveau.get("nom"),
                    abrege = niveau.get("abrege"),
                )
                nouveau_niveau.save()

    def ajouter_classes(self, ecole, classe_list):
        for classe in classe_list:
            niveau = NiveauScolaire.objects.filter(nom=classe.get("niveau_nom")).first()
            classe = Classe(
                ecole = ecole,
                nom = classe.get("nom"),
                date_debut = classe.get("date_debut"),
                date_fin = classe.get("date_fin"),
            )
            classe.save()
            classe.niveaux.add(niveau)
