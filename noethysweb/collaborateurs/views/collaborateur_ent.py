from django.views.generic import TemplateView
from core.views.base import CustomView
from django.db import transaction
from core.models import Collaborateur, GroupeCollaborateurs
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
import logging
from django.contrib import messages
from core.utils.utils_ent import get_collaborateur_by_ent_id
from collaborateurs.views.collaborateur import Onglet
from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect

logger = logging.getLogger(__name__)



class EntListeCollaborateur(CustomView, TemplateView):
    menu_code = "collaborateur_recherche_ent"
    template_name = "collaborateurs/collaborateur_recherche_ent.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['collaborateurs'] = self.request.session.get('collaborateurs_ent', [])
        context['page_titre'] = "Liste des collaborateurs de l'ENT"

        # Récupération des informations de recherche depuis la session
        search_info = self.request.session.get('collaborateur_search_info', {})
        context['search_nom'] = search_info.get('nom', '')
        context['search_prenom'] = search_info.get('prenom', '')
        context['search_categorie'] = search_info.get('categorie', '')

        return context
    
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        search_info = self.request.session.get('collaborateur_search_info', {})
        collaborateur_id = request.POST.get("collaborateur_id")
        collaborateurs = self.request.session.get('collaborateurs_ent', [])
        if action == "ajouter_nouveau_collaborateur":
            collaborateur = Collaborateur(
                nom = search_info.get("nom"),
                prenom = search_info.get("prenom"),
                civilite = search_info.get("civilite"),
            )
            collaborateur.save()
            groupes_ids = search_info.get("groupes", [])
            if groupes_ids:
                groupes_qs = GroupeCollaborateurs.objects.filter(idgroupe__in=groupes_ids)
                collaborateur.groupes.set(groupes_qs)
            collaborateur.save()
            url_success = reverse_lazy("collaborateur_resume", kwargs={'idcollaborateur': collaborateur.idcollaborateur})
        else:
            collaborateur = Collaborateur.objects.filter(ent_id=collaborateur_id).first()
            if not collaborateur:
                collaborateur_ent = self.trouver_collaborateur_par_ent_id(collaborateur_id, collaborateurs)
                collaborateur = Collaborateur(
                    civilite = search_info.get("civilite"),
                    nom = collaborateur_ent.get("nom"),
                    nom_jfille = collaborateur_ent.get("nom_jfille"),
                    prenom = collaborateur_ent.get("prenom"),
                    ent_id = collaborateur_ent.get("ent_id"),
                    rue_resid = collaborateur_ent.get("rue"),
                    cp_resid = collaborateur_ent.get("code_postal"),
                    ville_resid = collaborateur_ent.get("ville"),
                    travail_tel = collaborateur_ent.get("travail_tel"),
                    travail_mail = collaborateur_ent.get("travail_mail"),
                    tel_domicile = collaborateur_ent.get("tel_domicile"),
                    tel_mobile = collaborateur_ent.get("tel_mobile"),
                    mail = collaborateur_ent.get("mail"),
                )
                                
                collaborateur.save()
                groupes_ids = search_info.get("groupes", [])
                if groupes_ids:
                    groupes_qs = GroupeCollaborateurs.objects.filter(idgroupe__in=groupes_ids)
                    collaborateur.groupes.set(groupes_qs)
                    collaborateur.save()
                messages.add_message(self.request, messages.SUCCESS, "Ajout enregistré")
            else:
                messages.add_message(self.request, messages.ERROR, "Collaborateur existe déjà")
            url_success = reverse_lazy("collaborateur_resume", kwargs={'idcollaborateur': collaborateur.idcollaborateur})    
        return HttpResponseRedirect(url_success)

    def trouver_collaborateur_par_ent_id(self, colaborateur_id, collaborateurs):
        """
        Trouve un individu dans les données de session par son id_ent
        """        
        for col in collaborateurs:
            if str(col.get("ent_id")) == str(colaborateur_id):
                return col
        return None
    

class SynchroniserCollaborateur(Onglet, TemplateView):
    menu_code = "collaborateur_synchroniser"
    template_name = "collaborateurs/collaborateur_synchronisation.html"

    def get_context_data(self, **kwargs):
        context = super(SynchroniserCollaborateur, self).get_context_data(**kwargs)
        context['box_titre'] = "Synchronisation"
        context['onglet_actif'] = "synchroniser"
        collab = Collaborateur.objects.get(pk=self.kwargs['idcollaborateur'])

        # Mapping des champs avec leurs labels
        fields_mapping = [
            {'key': 'civilite', 'label': 'Civilité', 'local_key': 'civilite', 'external_key': 'civilite'},
            {'key': 'nom', 'label': 'Nom', 'local_key': 'nom', 'external_key': 'nom'},
            {'key': 'nom_jfille', 'label': 'Nom de jeune fille', 'local_key': 'nom_jfille', 'external_key': 'nom_jfille'},
            {'key': 'prenom', 'label': 'Prénom', 'local_key': 'prenom', 'external_key': 'prenom'},
            {'key': 'rue', 'label': 'Rue', 'local_key': 'rue', 'external_key': 'rue'},
            {'key': 'cp', 'label': 'Code postal', 'local_key': 'cp', 'external_key': 'code_postal'},
            {'key': 'ville', 'label': 'Ville', 'local_key': 'ville', 'external_key': 'ville'},
            {'key': 'travail_tel', 'label': 'Téléphone travail', 'local_key': 'travail_tel', 'external_key': 'travail_tel'},
            {'key': 'travail_mail', 'label': 'Mail travail', 'local_key': 'travail_mail', 'external_key': 'travail_mail'},
            {'key': 'tel_domicile', 'label': 'Téléphone domicile', 'local_key': 'tel_domicile', 'external_key': 'tel_domicile'},
            {'key': 'tel_mobile', 'label': 'Téléphone mobile', 'local_key': 'tel_mobile', 'external_key': 'tel_mobile'},
            {'key': 'mail', 'label': 'Mail personnel', 'local_key': 'mail', 'external_key': 'mail'},
        ]

        local_data = {
            "id": collab.idcollaborateur,
            "nom": collab.nom,
            "prenom": collab.prenom,
            "civilite": collab.civilite,
            "nom_jfille": collab.nom_jfille if hasattr(collab, 'nom_jfille') else None,
            "rue": collab.rue_resid,
            "cp": collab.cp_resid,
            "ville": collab.ville_resid,
            "travail_tel": collab.travail_tel,
            "travail_mail": collab.travail_mail,
            "tel_domicile": collab.tel_domicile,
            "tel_mobile": collab.tel_mobile,
            "mail": collab.mail
        }

        external_data = get_collaborateur_by_ent_id(collab.ent_id)

        context["collaborateur"] = collab
        context["local"] = local_data
        context["external"] = external_data
        context["fields_mapping"] = fields_mapping
        context["box_titre"] = f"Synchronisation - {collab.prenom} {collab.nom}"
        context["box_introduction"] = "Sélectionnez les champs à synchroniser depuis l'ENT vers CoCliCo."
        context["onglet_actif"] = "synchronisation"
        return context

    def post(self, request, *args, **kwargs):
        """Traite la synchronisation des champs sélectionnés"""
        try:
            collab = Collaborateur.objects.get(pk=self.kwargs['idcollaborateur'])
            external_data = get_collaborateur_by_ent_id(collab.ent_id)
            
            # Récupérer les champs sélectionnés
            selected_fields = request.POST.getlist('sync_fields')
            
            if not selected_fields:
                messages.warning(request, "Aucun champ sélectionné pour la synchronisation.")
                return redirect(request.path)
            
            # Mapping des champs du formulaire vers les attributs du modèle
            field_mapping = {
                'civilite': 'civilite',
                'nom': 'nom',
                'nom_jfille': 'nom_jfille',
                'prenom': 'prenom',
                'rue': 'rue_resid',
                'cp': 'cp_resid',
                'ville': 'ville_resid',
                'travail_tel': 'travail_tel',
                'travail_mail': 'travail_mail',
                'tel_domicile': 'tel_domicile',
                'tel_mobile': 'tel_mobile',
                'mail': 'mail'
            }
            
            # Mapping des champs externes
            external_field_mapping = {
                'civilite': 'civilite',
                'nom': 'nom',
                'nom_jfille': 'nom_jfille',
                'prenom': 'prenom',
                'rue': 'rue',
                'cp': 'code_postal',
                'ville': 'ville',
                'travail_tel': 'travail_tel',
                'travail_mail': 'travail_mail',
                'tel_domicile': 'tel_domicile',
                'tel_mobile': 'tel_mobile',
                'mail': 'mail'
            }
            
            updated_fields = []
            for field in selected_fields:
                if field in field_mapping:
                    model_field = field_mapping[field]
                    external_field = external_field_mapping[field]
                    
                    if external_field in external_data:
                        new_value = external_data[external_field]
                        setattr(collab, model_field, new_value)
                        updated_fields.append(field)
            
            if updated_fields:
                collab.save()
                messages.success(
                    request, 
                    f"Synchronisation réussie ! {len(updated_fields)} champ(s) mis à jour : {', '.join(updated_fields)}"
                )
            else:
                messages.info(request, "Aucun champ n'a été mis à jour.")
            
            return redirect(request.path)
            
        except Collaborateur.DoesNotExist:
            messages.error(request, "Collaborateur introuvable.")
            return redirect('collaborateurs_liste')
        except Exception as e:
            messages.error(request, f"Erreur lors de la synchronisation : {str(e)}")
            return redirect(request.path)
        
        