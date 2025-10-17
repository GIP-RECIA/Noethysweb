from core.models import Scolarite, Individu, Classe, NiveauScolaire, Ecole
from fiche_individu.views.individu import Onglet
from django.views.generic import TemplateView
from core.views.base import CustomView
from django.contrib import messages
from core.utils.utils_ent import get_ent_user_info_by_ent_id
from django.shortcuts import redirect
from django.db.models import Q

class UpdateIndividu(Onglet, TemplateView):
    menu_code = "individu_synchroniser"
    template_name = "fiche_individu/individu_update_ent.html"

    def get_context_data(self, **kwargs):
        context = super(UpdateIndividu, self).get_context_data(**kwargs)
        context['box_titre'] = "Synchronisation"
        context['onglet_actif'] = "synchroniser"
        individu = Individu.objects.get(pk=self.kwargs['idindividu'])

        # Récupérer les données externes
        external_data = get_ent_user_info_by_ent_id(individu.ent_id)
        
        # Vérifier si l'utilisateur existe dans l'ENT
        if not external_data:
            context["individu"] = individu
            context["user_not_found"] = True
            context["box_titre"] = f"Synchronisation - {individu.prenom} {individu.nom}"
            context["box_introduction"] = "Cet utilisateur n'a pas été trouvé dans l'ENT."
            context["onglet_actif"] = "synchronisation"
            return context
        
        # Préparer les données locales
        local_data = {
            "id": individu.idindividu,
            "civilite": individu.get_civilite_display() if individu.civilite else None,
            "nom": individu.nom,
            "prenom": individu.prenom,
            "nom_jfille": individu.nom_jfille,
            "rue": individu.rue_resid,
            "cp": individu.cp_resid,
            "ville": individu.ville_resid,
            "tel_mobile": individu.tel_mobile,
            "mail": individu.mail,
        }
        
        # Préparer les données externes avec mapping
        external_display = {
            "civilite": external_data.get('civilite'),
            "nom": external_data.get('nom'),
            "prenom": external_data.get('prenom'),
            "nom_jfille": external_data.get('nom_jfille'),
            "rue": external_data.get('rue'),
            "cp": external_data.get('cp'),
            "ville": external_data.get('ville'),
            "tel_mobile": external_data.get('telephone'),
            "mail": external_data.get('email'),
        }
        
        # Si c'est un enfant avec scolarité
        has_scolarite = 'scolarite' in external_data and external_data['scolarite']
        if has_scolarite:
            scolarite = external_data['scolarite']
            ecole = scolarite.get('ecole', {})
            classe = scolarite.get('classe', {})
            niveau = scolarite.get('niveau', {})
            
            # Ajouter les informations de scolarité
            external_display.update({
                'ecole_nom': ecole.get('nom'),
                'ecole_rue': ecole.get('rue'),
                'ecole_cp': ecole.get('cp'),
                'ecole_ville': ecole.get('ville'),
                'classe_nom': classe.get('nom'),
                'niveau_nom': niveau.get('nom'),
            })
            
            local_data.update({
                'ecole_nom': None,
                'ecole_rue': None,
                'ecole_cp': None,
                'ecole_ville': None,
                'classe_nom': None,
                'niveau_nom': None,
            })

        # Mapping des champs avec leurs labels
        fields_mapping = [
            {'key': 'civilite', 'label': 'Civilité', 'local_key': 'civilite', 'external_key': 'civilite'},
            {'key': 'nom', 'label': 'Nom', 'local_key': 'nom', 'external_key': 'nom'},
            {'key': 'nom_jfille', 'label': 'Nom de jeune fille', 'local_key': 'nom_jfille', 'external_key': 'nom_jfille'},
            {'key': 'prenom', 'label': 'Prénom', 'local_key': 'prenom', 'external_key': 'prenom'},
            {'key': 'rue', 'label': 'Rue', 'local_key': 'rue', 'external_key': 'rue'},
            {'key': 'cp', 'label': 'Code postal', 'local_key': 'cp', 'external_key': 'cp'},
            {'key': 'ville', 'label': 'Ville', 'local_key': 'ville', 'external_key': 'ville'},
            {'key': 'tel_mobile', 'label': 'Téléphone mobile', 'local_key': 'tel_mobile', 'external_key': 'tel_mobile'},
            {'key': 'mail', 'label': 'Mail personnel', 'local_key': 'mail', 'external_key': 'mail'},
        ]
        
        # Ajouter les champs de scolarité si applicable
        if has_scolarite:
            fields_mapping.extend([
                {'key': 'ecole_nom', 'label': 'École', 'local_key': 'ecole_nom', 'external_key': 'ecole_nom'},
                {'key': 'classe_nom', 'label': 'Classe', 'local_key': 'classe_nom', 'external_key': 'classe_nom'},
                {'key': 'niveau_nom', 'label': 'Niveau', 'local_key': 'niveau_nom', 'external_key': 'niveau_nom'},
            ])

        context["individu"] = individu
        context["local"] = local_data
        context["external"] = external_display
        context["fields_mapping"] = fields_mapping
        context["has_scolarite"] = has_scolarite
        context["box_titre"] = f"Synchronisation - {individu.prenom} {individu.nom}"
        context["box_introduction"] = "Sélectionnez les champs à synchroniser depuis l'ENT vers CoCliCo."
        context["onglet_actif"] = "synchronisation"
        return context

    def post(self, request, *args, **kwargs):
        """Traite la synchronisation des champs sélectionnés"""
        try:
            individu = Individu.objects.get(pk=self.kwargs['idindividu'])
            external_data = get_ent_user_info_by_ent_id(individu.ent_id)
            
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
                'tel_mobile': 'tel_mobile',
                'mail': 'mail'
            }
            
            # Mapping des champs externes (API) vers les clés
            external_field_mapping = {
                'civilite': 'civilite',
                'nom': 'nom',
                'nom_jfille': 'nom_jfille',
                'prenom': 'prenom',
                'rue': 'rue',
                'cp': 'cp',
                'ville': 'ville',
                'tel_mobile': 'telephone',
                'mail': 'email'
            }
            
            updated_fields = []
            for field in selected_fields:
                if field in field_mapping:
                    model_field = field_mapping[field]
                    external_field = external_field_mapping[field]
                    
                    if external_field in external_data:
                        new_value = external_data[external_field]
                        
                        # Traitement spécial pour civilite (conversion texte vers ID)
                        if field == 'civilite' and new_value:
                            # Mapper les civilités texte vers les IDs du modèle
                            civilite_mapping = {
                                'M.': 1,  # Ajustez selon vos choix de civilité
                                'Mme': 2,
                                'Mlle': 3,
                            }
                            new_value = civilite_mapping.get(new_value, individu.civilite)
                        
                        setattr(individu, model_field, new_value)
                        updated_fields.append(field)
            
            # Gérer les champs de scolarité si présents (nécessite adaptation selon votre modèle)
            if 'scolarite' in external_data and external_data['scolarite']:
                # TODO: Implémenter la synchronisation de la scolarité selon votre modèle
                # Exemple: créer ou mettre à jour les inscriptions, écoles, classes, etc.
                pass
            
            if updated_fields:
                individu.save()
                messages.success(
                    request, 
                    f"Synchronisation réussie ! {len(updated_fields)} champ(s) mis à jour : {', '.join(updated_fields)}"
                )
            else:
                messages.info(request, "Aucun champ n'a été mis à jour.")
            
            return redirect(request.path)
            
        except Individu.DoesNotExist:
            messages.error(request, "Individu introuvable.")
            return redirect('individus_liste')
        except Exception as e:
            messages.error(request, f"Erreur lors de la synchronisation : {str(e)}")
            return redirect(request.path)
        




class SynchronisationMasseIndividus(CustomView, TemplateView):
    template_name = "fiche_individu/individu_liste_maj.html"
    menu_code = "mettre_a_jour_liste_individu_ent"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
         # Récupérer uniquement le filtre de recherche textuelle
        search_query = self.request.GET.get('search', '')
        
        # Base query - Tous les individus avec ENT ID par défaut
        individus = Individu.objects.filter(ent_id__isnull=False).exclude(ent_id='').order_by('nom', 'prenom')
        
        # Recherche textuelle
        
        # if search_query:
        #     individus = individus.filter(
        #         Q(nom__icontains=search_query) |
        #         Q(prenom__icontains=search_query) |
        #         Q(ent_id__icontains=search_query) |
        #         Q(mail__icontains=search_query)
        #     )
        
        # Récupérer la liste des écoles - Non utilisé maintenant
        ecoles = []
        
        # Préparer les données des individus
        individus_data = []
        for individu in individus[:200]:  # Limiter à 200 pour la performance
            # TODO: Récupérer l'école de l'individu selon votre modèle
            # Non utilisé pour l'instant
            
            individus_data.append({
                'id': individu.idindividu,
                'ent_id': individu.ent_id,
                'civilite': individu.get_civilite_display() if individu.civilite else "-",
                'nom': individu.nom,
                'prenom': individu.prenom or "-",
                'mail': individu.mail or "-",
                'tel_mobile': individu.tel_mobile or "-",
            })
        
        context['individus'] = individus_data
        context['total_count'] = individus.count()
        print(individus.count())
        context['total_all_individus'] = Individu.objects.count()
        print(Individu.objects.count())
        # context['search_query'] = search_query
        # print(search_query)
        context['page_titre'] = "Synchronisation en masse"
        context['box_titre'] = "Synchronisation en masse depuis l'ENT"
        context['box_introduction'] = "Visualisez tous les individus avec un ENT ID et sélectionnez ceux à synchroniser avec les données de l'ENT."
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Lance la synchronisation en masse des individus sélectionnés"""
        try:
            # Récupérer les IDs des individus sélectionnés
            selected_ids = request.POST.getlist('selected_individus')
            
            if not selected_ids:
                messages.warning(request, "Aucun individu sélectionné pour la synchronisation.")
                return redirect(request.path)
            
            # Convertir en integers
            selected_ids = [int(id) for id in selected_ids]
            
            # TODO: Implémenter la logique de synchronisation en masse
            # Cette fonction sera développée ultérieurement
            success_count = self.synchroniser_individus_masse(selected_ids)
            
            if success_count > 0:
                messages.success(
                    request,
                    f"Synchronisation lancée avec succès pour {success_count} individu(s)."
                )
            else:
                messages.info(request, "Aucune synchronisation effectuée.")
            
            return redirect(request.path + f"?{request.GET.urlencode()}")
            
        except Exception as e:
            messages.error(request, f"Erreur lors de la synchronisation : {str(e)}")
            return redirect(request.path)
    
    def synchroniser_individus_masse(self, individu_ids):
        """
        TODO: Fonction à développer pour la synchronisation en masse
        
        Args:
            individu_ids: Liste des IDs des individus à synchroniser
            
        Returns:
            int: Nombre d'individus synchronisés avec succès
        """
        # Cette fonction sera implémentée plus tard
        # Pour l'instant, elle ne fait rien
        
        # Logique à implémenter:
        # 1. Pour chaque individu_id:
        #    - Récupérer l'individu
        #    - Appeler get_ent_user_info(individu.ent_id)
        #    - Mettre à jour les champs si données disponibles
        #    - Gérer les erreurs individuellement
        # 2. Retourner le nombre de synchronisations réussies
        
        return len(individu_ids)  # Placeholder