from django.views.generic import TemplateView
from core.views.base import CustomView
from django.db import transaction
from core.utils import utils_questionnaires
from fiche_famille.utils import utils_internet
from core.models import Individu, Famille, Rattachement, Utilisateur, Ecole, Classe, Scolarite, NiveauScolaire
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
import logging
from django.contrib import messages
from django.http import JsonResponse
from core.utils.utils_ent import get_ent_user_info, get_enfant_famille
from core.data import data_civilites
import time
import json

logger = logging.getLogger(__name__)



class EntListeIndividus(CustomView, TemplateView):
    menu_code = "ent_liste_individus"
    template_name = "fiche_famille/famille_ent_liste.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        idfamille = kwargs.get("idfamille", None)
        context['rattachements'] = self.request.session.get('ent_users_data', [])
        context['page_titre'] = "Liste des familles de l'ENT"

        # Récupération des informations de recherche depuis la session
        search_info = self.request.session.get('search_info', {})
        context['search_nom'] = search_info.get('nom', '')
        context['search_prenom'] = search_info.get('prenom', '')
        context['search_categorie'] = search_info.get('categorie', '')

        if idfamille:
            context["mode"] = "individus"
            context["idfamille"] = int(idfamille)
        else:
            context["mode"] = "familles"
        return context
    
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        idfamille = kwargs.get("idfamille", None)
        search_info = self.request.session.get('search_info', {})
        # Ce parametre est utilisé pour identifier s'il s'agit d'importer toute une famille de l'ent ou juste un individu à une famille
        individu_id = request.POST.get("individu_id")

        # L'action est utilisée pour savoir si l'on veut simplement ajouter un nouvel individu indépendamment des données de l'ENT
        if action == "ajouter_nouvel_individu":
            # idfamille est utilisé pour vérifier s'il s'agit dun ajout d'un individu à une famille existante deja
            if idfamille:
                new_famille = Famille.objects.get(pk=idfamille)
            else:
                new_famille = self.creation_famille()
            self.creation_nouvel_individu(search_info, new_famille)
            new_famille.Maj_infos()
            url_success = reverse_lazy("famille_resume", kwargs={'idfamille': new_famille.pk})

        # Nouvelle action pour ajouter uniquement un représentant
        elif action == "ajouter_representant":
            familles = request.session.get("ent_users_data", [])

            if not individu_id:
                messages.add_message(self.request, messages.ERROR, "Identifiant du représentant manquant")
                return HttpResponseRedirect(reverse_lazy("ent_liste_familles"))

            # Trouver le représentant dans les données de session
            individu_trouve = self.trouver_individu_par_ent_id(individu_id, familles)

            if not individu_trouve:
                messages.add_message(self.request, messages.ERROR, "Représentant introuvable")
                return HttpResponseRedirect(reverse_lazy("ent_liste_familles"))

            # Vérifier si on ajoute à une famille existante ou si on crée une nouvelle famille
            if idfamille:
                new_famille = Famille.objects.get(pk=idfamille)
            else:
                # Vérifier si ce représentant existe déjà dans une famille
                existing_individu = Individu.objects.filter(ent_id=individu_id).first()
                if existing_individu:
                    existing_rattachement = Rattachement.objects.filter(individu=existing_individu, categorie__in=[1, 3]).first()
                    if existing_rattachement:
                        messages.add_message(self.request, messages.ERROR, "Ce représentant existe déjà dans une famille")
                        return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={'idfamille': existing_rattachement.famille.pk}))

                # Créer une nouvelle famille
                new_famille = self.creation_famille()

            # Ajouter le représentant (catégorie 1)
            self.creation_individu_ent(individu_trouve, new_famille, 1)
            new_famille.Maj_infos()

            messages.add_message(self.request, messages.SUCCESS, "Représentant ajouté avec succès")
            url_success = reverse_lazy("famille_resume", kwargs={'idfamille': new_famille.pk})

        else:
            familles = request.session.get("ent_users_data", [])
            if idfamille:
                new_famille = Famille.objects.get(pk=idfamille)
                if individu_id:
                    individu_trouve = self.trouver_individu_par_ent_id(individu_id, familles)
                    self.creation_individu_ent(individu_trouve, new_famille, search_info.get('categorie', ''))
            else:
                index = int(request.POST.get("famille_index"))
                famille = familles[index]
                # Avant de créer la famille, on vérifie si l'un des enfants appartient déjà à une famille dans la base (dans ce cas, cette famille existe déjà).
                # Si une telle famille existe, on redirige alors l'utilisateur vers la fiche de cette famille.
                new_famille = self.chercher_famille_avec_ent_id(famille)
                if new_famille:
                     messages.add_message(self.request, messages.ERROR, "Famille existe déjà")
                else:
                    new_famille = self.creation_famille()
                    for indiv in famille["representants"]:
                        self.creation_individu_ent(indiv, new_famille, 1)

                    for enf in famille["enfants"]:
                        self.creation_individu_ent(enf, new_famille, 2)
                    new_famille.Maj_infos()
            url_success = reverse_lazy("famille_resume", kwargs={'idfamille': new_famille.pk})

        return HttpResponseRedirect(url_success)


    def trouver_individu_par_ent_id(self, individu_id, familles):
        """
        Trouve un individu dans les données de session par son id_ent
        """
        for famille in familles:
            # Chercher dans les représentants
            if str(famille.get("representant", None).get("id_ent")) == str(individu_id):
                return famille.get("representant", None)
            
            # Chercher dans les enfants
            for enfant in famille.get("enfants", []):
                if str(enfant.get("id_ent")) == str(individu_id):
                    return enfant
        
        return None
    
    @transaction.atomic
    def creation_famille(self):
        """ Le transaction.atomic permet de faire que les enregistrements suivants soient tous effectués en même temps dans la db """
        famille = Famille.objects.create()

        # Création des questionnaires de type famille
        utils_questionnaires.Creation_reponses(categorie="famille", liste_instances=[famille])

        # Création et enregistrement des codes pour le portail
        internet_identifiant = utils_internet.CreationIdentifiant(IDfamille=famille.pk)
        internet_mdp, date_expiration_mdp = utils_internet.CreationMDP()

        # Mémorisation des codes internet dans la table familles
        famille.internet_identifiant = internet_identifiant
        famille.internet_mdp = internet_mdp

        # Création de l'utilisateur
        utilisateur = Utilisateur(username=internet_identifiant, categorie="famille", force_reset_password=True, date_expiration_mdp=date_expiration_mdp)
        utilisateur.set_password(internet_mdp)
        utilisateur.save()
        # Association de l'utilisateur à la famille
        famille.utilisateur = utilisateur
        famille.save()
        return famille


    @transaction.atomic
    def creation_nouvel_individu(self, new_indiv, famille):
        categorie = new_indiv.get("categorie")
        individu = Individu(
            # Attributs principaux
            prenom=new_indiv.get("prenom"),
            nom=new_indiv.get("nom"),
            civilite=new_indiv.get("civilite")
        )
        individu.save()
        # Création des questionnaires de type individu
        utils_questionnaires.Creation_reponses(categorie="individu", liste_instances=[individu])
        internet_identifiant_individu = utils_internet.CreationIdentifiantIndividu(IDindividu=individu.pk)
        internet_mdp_individu, date_expiration_mdp_individu = utils_internet.CreationMDP()
        individu.internet_identifiant = internet_identifiant_individu
        individu.internet_mdp = internet_mdp_individu

        # Vous pouvez aussi créer un utilisateur pour l'individu si nécessaire
        utilisateur_individu = Utilisateur(
            username=internet_identifiant_individu,
            categorie="individu",  # Ou une autre catégorie, selon votre besoin
            force_reset_password=True,
            date_expiration_mdp=date_expiration_mdp_individu
        )
        utilisateur_individu.set_password(internet_mdp_individu)
        utilisateur_individu.save()

        # Association de l'utilisateur à l'individu
        individu.utilisateur = utilisateur_individu
        individu.save()
        titulaire = 1 if categorie!=2 else 0
        rattachement = Rattachement(famille=famille, individu=individu, categorie=categorie, titulaire=titulaire)
        rattachement.save()

    
    @transaction.atomic
    def creation_individu_ent(self, new_indiv, famille, categorie):
        individu = Individu.objects.filter(ent_id=new_indiv.get("id_ent")).first()
        if not individu:
            individu = Individu(
                # Attributs principaux
                prenom=new_indiv.get("prenom"),
                nom=new_indiv.get("nom"),
                civilite=1 if new_indiv.get("civilite") in ("M.", "Mr", "Monsieur") else 2,  # mapping simple
                mail=new_indiv.get("email"),
                tel_mobile=new_indiv.get("telephone"),
                internet_actif=True,
                ent_id=new_indiv.get("id_ent")
            )
            individu.save()
            # Création des questionnaires de type individu
            utils_questionnaires.Creation_reponses(categorie="individu", liste_instances=[individu])
            internet_identifiant_individu = utils_internet.CreationIdentifiantIndividu(IDindividu=individu.pk)
            internet_mdp_individu, date_expiration_mdp_individu = utils_internet.CreationMDP()
            individu.internet_identifiant = internet_identifiant_individu
            individu.internet_mdp = internet_mdp_individu

            # Vous pouvez aussi créer un utilisateur pour l'individu si nécessaire
            utilisateur_individu = Utilisateur(
                username=internet_identifiant_individu,
                categorie="individu",  # Ou une autre catégorie, selon votre besoin
                force_reset_password=True,
                date_expiration_mdp=date_expiration_mdp_individu
            )
            utilisateur_individu.set_password(internet_mdp_individu)
            utilisateur_individu.save()

            # Association de l'utilisateur à l'individu
            individu.utilisateur = utilisateur_individu
            individu.save()
        titulaire = 1 if categorie==1 else 0
        rattachement = Rattachement(famille=famille, individu=individu, categorie=categorie, titulaire=titulaire)
        rattachement.save()
        if new_indiv.get("scolarite"):
            self.creation_scolarite(individu, new_indiv.get("scolarite"))


    @transaction.atomic
    def creation_scolarite(self, new_indiv, scolarite):
        # Vérifie si cet utilisateur a déjà une scolarité
        scolarite_ancienne = Scolarite.objects.filter(individu=new_indiv).first()
        if not scolarite_ancienne:
            # Création / récupération école
            ecole= Ecole.objects.filter(
                uai=scolarite.get("ecole", {}).get("uai")).first()

            # Création / récupération classe
            classe= Classe.objects.get_or_create(
                nom=scolarite.get("classe", {}).get("nom"),ecole=ecole).first()

            # Création / récupération niveau
            niveau= NiveauScolaire.objects.filter(nom=scolarite.get("niveau", {}).get("nom")).first()

            # Création scolarité
            scolarite_obj = Scolarite.objects.create(
                individu=new_indiv,
                date_debut=scolarite.get("date_debut"),
                date_fin=scolarite.get("date_fin"),
                ecole=ecole,
                classe=classe,
                niveau=niveau
            )
            scolarite_obj.save()


    def chercher_famille_avec_ent_id(self, famille_ent):
        # Cette fonction vérifie si une famille existe déjà en utilisant les ent_id des enfants
        for enfant in famille_ent.get("enfants", []):
            rattachemnt = Rattachement.objects.filter(individu__ent_id = enfant.get("id_ent", "")).first()
            if rattachemnt:
                return rattachemnt.famille
        return None
    
class FamillesSynchroView(CustomView, TemplateView):
    template_name = "fiche_famille/familles_synchro.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["familles_non_sync"] = self.get_familles_non_sync()
        context["page_titre"] = "Familles non synchronisées"
        return context
    
    def get_familles_non_sync(self):
        rattachements = Rattachement.objects.filter(individu__ent_id__isnull=True)
        familles = Famille.objects.filter(idfamille__in=rattachements.values_list('famille_id', flat=True).distinct())
        return familles
    
    def post(self, request, *args, **kwargs):
        """Gérer la synchronisation d'une famille"""
        try:
            # Vérifier si c'est une requête JSON (validation) ou form data (vérification)
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                action = data.get('action')
                logger.info(f"Action: {action}")
                
                if action == 'validate':
                    return self.valider_synchronisation(data)
            
            # Sinon, c'est une vérification classique
            famille_id = request.POST.get('famille_id')
            logger.info(f"Vérification de la famille ID: {famille_id}")
            time.sleep(1)
            
            famille = Famille.objects.get(idfamille=famille_id)
            logger.info(f"Famille trouvée: {famille}")
            
            differences = self.comparer_famille(famille)
            logger.info(f"Différences trouvées: {len(differences.get('representants', []))} représentants, {len(differences.get('enfants', []))} enfants")
            
            return JsonResponse({
                'success': True,
                'differences': differences
            })
            
        except Famille.DoesNotExist:
            logger.error(f"Famille {famille_id} introuvable")
            return JsonResponse({
                'success': False,
                'error': 'Famille introuvable'
            }, status=404)
        except Exception as e:
            logger.exception(f"Erreur dans post(): {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    def valider_synchronisation(self, data):
        """
        Valide et applique les modifications sélectionnées
        """
        try:
            famille_id = data.get('famille_id')
            selected_fields = data.get('selected_fields', {})
            
            if not selected_fields:
                return JsonResponse({
                    'success': False,
                    'error': 'Aucun champ sélectionné'
                }, status=400)
            
            famille = Famille.objects.get(idfamille=famille_id)
            updated_count = 0
            errors = []
            
            # Traiter chaque individu séparément avec sa propre transaction
            for key, person_data in selected_fields.items():
                individu_id = person_data.get('id')
                person_type = person_data.get('type')
                fields_to_update = person_data.get('fields', [])
                # Récupérer l'index de la personne sélectionnée (si plusieurs personnes avec même nom/prénom)
                index_personne = person_data.get('index_personne', 0)

                try:
                    # Transaction séparée pour chaque individu
                    with transaction.atomic():
                        # Récupérer l'individu
                        individu = Individu.objects.select_for_update().get(idindividu=individu_id)

                        # Récupérer les données de l'API (toutes les personnes avec ce nom/prénom)
                        ent_results = get_ent_user_info(individu.nom, individu.prenom)

                        if not ent_results:
                            errors.append(f"{individu.prenom} {individu.nom}: Données API introuvables")
                            continue

                        # S'assurer que c'est une liste
                        if not isinstance(ent_results, list):
                            ent_results = [ent_results]

                        # Sélectionner la bonne personne selon l'index
                        if index_personne >= len(ent_results):
                            errors.append(f"{individu.prenom} {individu.nom}: Index de personne invalide")
                            continue

                        individu_api = ent_results[index_personne]
                        
                        # Appliquer les modifications pour chaque champ sélectionné
                        for field_label in fields_to_update:
                            result = self.appliquer_modification(individu, individu_api, field_label)
                            if result['success']:
                                updated_count += 1
                            else:
                                errors.append(f"{individu.prenom} {individu.nom} - {field_label}: {result['error']}")
                        individu.ent_id = individu_api.get("ent_id", None)
                        # Sauvegarder l'individu
                        individu.save()
                        
                except Individu.DoesNotExist:
                    errors.append(f"Individu ID {individu_id} introuvable")
                except Exception as e:
                    errors.append(f"Erreur pour l'individu ID {individu_id}: {str(e)}")
            
            response_data = {
                'success': True,
                'updated_count': updated_count,
                'message': f'{updated_count} champ(s) mis à jour avec succès'
            }
            
            if errors:
                response_data['warnings'] = errors
            
            return JsonResponse(response_data)
            
        except Famille.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Famille introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Erreur lors de la synchronisation: {str(e)}'
            }, status=500)
    
    def appliquer_modification(self, individu, individu_api, field_label):
        """
        Applique une modification à un individu à partir des données API
        Retourne un dict avec 'success' et 'error' si applicable
        """
        # Mapping inverse: label français -> (champ DB, champ API)
        field_mapping = {
            'Nom': ('nom', 'nom'),
            'Prénom': ('prenom', 'prenom'),
            'Civilité': ('civilite', 'civilite'),
            'Date de naissance': ('date_naiss', 'date_naissance'),
            'Code postal de naissance': ('cp_naiss', 'code_postal_naissance'),
            'Ville de naissance': ('ville_naiss', 'ville_naissance'),
            'Email': ('mail', 'email'),
            'Téléphone mobile': ('tel_mobile', 'telephone_mobile'),
            'Téléphone domicile': ('tel_domicile', 'telephone'),
            'Adresse': ('adresse_auto', 'adresse'),
            'Code postal': ('cp_auto', 'code_postal'),
            'Ville': ('ville_auto', 'ville'),
            'ID ENT': ('ent_id', 'ent_id'),
        }
        
        if field_label not in field_mapping:
            return {'success': False, 'error': 'Champ inconnu'}
        
        champ_db, champ_api = field_mapping[field_label]
        
        try:
            # Extraire la valeur de l'API
            valeur_api = self.extraire_valeur_api(individu_api, champ_api)
            
            if valeur_api is None:
                return {'success': False, 'error': 'Valeur API introuvable'}
            
            # Traitement spécial pour la civilité
            if champ_db == 'civilite':
                valeur_api = self.convertir_civilite(valeur_api)
            
            # Traitement spécial pour les dates
            if champ_db == 'date_naiss' and isinstance(valeur_api, str):
                from datetime import datetime
                try:
                    # Essayer différents formats de date
                    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
                        try:
                            valeur_api = datetime.strptime(valeur_api, fmt).date()
                            break
                        except ValueError:
                            continue
                except:
                    return {'success': False, 'error': f'Format de date invalide: {valeur_api}'}
            
            # Appliquer la valeur
            setattr(individu, champ_db, valeur_api)
            return {'success': True}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def convertir_civilite(self, valeur):
        """
        Convertit la civilité de l'API en valeur compatible avec la base de données
        Utilise le dictionnaire data_civilites pour la conversion
        """
        from django.db.models import CharField, IntegerField

        field = Individu._meta.get_field('civilite')

        if isinstance(field, IntegerField):
            # Créer un mapping inverse à partir de data_civilites
            dict_civilites_data = data_civilites.GetDictCivilites()

            # Mapping: texte API -> ID civilité
            mapping_civilite = {}
            for civ_id, civ_info in dict_civilites_data.items():
                # Ajouter le label complet
                if civ_info.get('label'):
                    mapping_civilite[civ_info['label']] = civ_id
                # Ajouter l'abrégé si disponible
                if civ_info.get('abrege'):
                    mapping_civilite[civ_info['abrege']] = civ_id

            # Ajouter des variations courantes
            variations = {
                'M': 1,
                'M.': 1,
                'Mr': 1,
                'Melle': 2,  # Correspond à Mademoiselle (id 2)
                'Mlle': 2,
            }
            mapping_civilite.update(variations)

            return mapping_civilite.get(valeur, 1)  # Par défaut Monsieur (id=1)

        elif isinstance(field, CharField):
            # Si c'est un CharField, retourner la valeur normalisée
            return valeur

        else:
            # Si c'est une ForeignKey, il faudrait récupérer l'objet correspondant
            return valeur
    
    def comparer_famille(self, famille):
        """
        Compare les données de chaque membre de la famille avec l'API.
        Si plusieurs personnes dans l'ENT ont le même nom/prénom, on affiche toutes les familles correspondantes.
        """
        differences = {
            'representants': [],
            'enfants': [],
            'info_recherche': None  # Info sur les résultats de recherche
        }

        rattachements = famille.rattachement_set.select_related('individu').all()

        for ratt in rattachements:
            individu = ratt.individu

            try:
                # get_ent_user_info retourne TOUTES les personnes avec ce nom/prénom
                ent_results = get_ent_user_info(individu.nom, individu.prenom)

                if ent_results:
                    # S'assurer que c'est toujours une liste
                    if not isinstance(ent_results, list):
                        ent_results = [ent_results]

                    nb_resultats = len(ent_results)

                    # Message informatif si plusieurs résultats
                    if nb_resultats > 1 and not differences['info_recherche']:
                        differences['info_recherche'] = {
                            'message': f"{nb_resultats} personnes trouvées avec le nom/prénom '{individu.prenom} {individu.nom}' dans l'ENT",
                            'type': 'warning'
                        }

                    # Afficher chaque personne trouvée dans l'ENT
                    for index, individu_api in enumerate(ent_results):
                        diff = self.comparer_individu(individu, individu_api)

                        # Créer le nom d'affichage
                        nom_affiche = f"{individu.prenom} {individu.nom}"

                        # Si plusieurs personnes, ajouter un badge pour différencier
                        if nb_resultats > 1:
                            # Récupérer des infos distinctives de l'API (email, téléphone, etc.)
                            info_distinctive = []
                            if individu_api.get('email'):
                                info_distinctive.append(f"Email: {individu_api.get('email')}")
                            if individu_api.get('telephone'):
                                info_distinctive.append(f"Tél: {individu_api.get('telephone')}")
                            if individu_api.get('adresse'):
                                info_distinctive.append(f"Ville: {individu_api.get('ville', '')}")

                            info_text = ' | '.join(info_distinctive[:2]) if info_distinctive else f"Personne {index + 1}"
                            nom_affiche += f" <span class='badge badge-info' style='font-size:0.8em;'>{info_text}</span>"

                        # Toujours afficher si plusieurs personnes, sinon seulement si différences
                        if diff or nb_resultats > 1:
                            diff_entry = {
                                'id': individu.idindividu,
                                'nom': nom_affiche,
                                'differences': diff or {},
                                'multiple_personnes': nb_resultats > 1,
                                'index_personne': index,
                                'total_personnes': nb_resultats,
                                'info_distinctive': individu_api.get('email', '') or individu_api.get('telephone', '')
                            }

                            if ratt.categorie in [1, 3]:
                                differences['representants'].append(diff_entry)
                            else:
                                differences['enfants'].append(diff_entry)
                else:
                    # Personne non trouvée dans l'ENT
                    diff_entry = {
                        'id': individu.idindividu,
                        'nom': f"{individu.prenom} {individu.nom}",
                        'differences': {
                            'statut': {
                                'old': 'En base de données',
                                'new': 'Non trouvé dans l\'ENT'
                            }
                        },
                        'multiple_personnes': False
                    }

                    if ratt.categorie in [1, 2]:
                        differences['representants'].append(diff_entry)
                    else:
                        differences['enfants'].append(diff_entry)

            except Exception as e:
                logger.exception(f"Erreur lors de la comparaison pour {individu.prenom} {individu.nom}")
                diff_entry = {
                    'id': individu.idindividu,
                    'nom': f"{individu.prenom} {individu.nom}",
                    'differences': {
                        'erreur': {
                            'old': 'Erreur',
                            'new': f'Erreur API: {str(e)}'
                        }
                    },
                    'multiple_personnes': False
                }

                if ratt.categorie in [1, 2]:
                    differences['representants'].append(diff_entry)
                else:
                    differences['enfants'].append(diff_entry)

        return differences
    
    def comparer_individu(self, individu_db, individu_api):
        """
        Compare un individu en base avec ses données API
        """
        differences = {}
        
        champs_a_comparer = {
            'nom': 'nom',
            'prenom': 'prenom',
            'civilite': 'civilite',
            'date_naiss': 'date_naissance',
            'cp_naiss': 'code_postal_naissance',
            'ville_naiss': 'ville_naissance',
            'mail': 'email',
            'tel_mobile': 'telephone_mobile',
            'tel_domicile': 'telephone',
            'adresse_auto': 'adresse',
            'cp_auto': 'code_postal',
            'ville_auto': 'ville',
            'ent_id': 'id',
        }
        
        for champ_db, champ_api in champs_a_comparer.items():
            valeur_db = getattr(individu_db, champ_db, None)
            valeur_api = self.extraire_valeur_api(individu_api, champ_api)

            # Passer le nom du champ pour traitement spécial (civilité, etc.)
            valeur_db_str = self.normaliser_valeur(valeur_db, champ_db)
            valeur_api_str = self.normaliser_valeur(valeur_api, champ_db)

            if valeur_db_str != valeur_api_str:
                nom_champ_affiche = self.traduire_nom_champ(champ_db)

                differences[nom_champ_affiche] = {
                    'old': valeur_db_str if valeur_db_str else '(vide)',
                    'new': valeur_api_str if valeur_api_str else '(vide)'
                }

        return differences if differences else None
    
    def extraire_valeur_api(self, individu_api, champ):
        """
        Extrait une valeur de l'objet API (qui peut être imbriqué)
        """
        if '.' in champ:
            keys = champ.split('.')
            valeur = individu_api
            for key in keys:
                if isinstance(valeur, dict):
                    valeur = valeur.get(key)
                else:
                    return None
            return valeur
        else:
            return individu_api.get(champ) if isinstance(individu_api, dict) else None
    
    def normaliser_valeur(self, valeur, champ_db=None):
        """
        Normalise une valeur pour la comparaison et l'affichage
        """
        if valeur is None or valeur == '':
            return ''

        # Traitement spécial pour la civilité
        if champ_db == 'civilite':
            # Récupérer le dictionnaire des civilités
            dict_civilites_data = data_civilites.GetDictCivilites()

            # Si c'est un nombre (valeur DB)
            if isinstance(valeur, int):
                civilite_info = dict_civilites_data.get(valeur)
                if civilite_info:
                    return civilite_info.get('abrege') or civilite_info.get('label', str(valeur))
                return str(valeur)

            # Si c'est déjà une chaîne (valeur API)
            if isinstance(valeur, str):         
                # Normaliser les variations courantes
                valeur_norm = valeur.strip()
                mapping_api_to_abrege = {
                    'M.': 'M.',
                    'M': 'M.',
                    'Monsieur': 'M.',
                    'Mr': 'M.',
                    'Mme': 'Mme',
                    'Madame': 'Mme',
                    'Melle': 'Melle',
                    'Mlle': 'Melle',
                    'Mademoiselle': 'Melle',
                }
                return mapping_api_to_abrege.get(valeur_norm, valeur_norm)

        # Traitement des dates
        if hasattr(valeur, 'strftime'):
            return valeur.strftime('%d/%m/%Y')

        valeur_str = str(valeur).strip()

        # Pour les numéros de téléphone, ne garder que les chiffres
        if valeur_str and any(char.isdigit() for char in valeur_str) and champ_db in ['tel_mobile', 'tel_domicile']:
            valeur_str = ''.join(filter(lambda x: x.isdigit() or x == '+', valeur_str))

        return valeur_str
    
    def traduire_nom_champ(self, champ_db):
        """
        Traduit les noms de champs techniques en français pour l'affichage
        """
        traductions = {
            'nom': 'Nom',
            'prenom': 'Prénom',
            'civilite': 'Civilité',
            'date_naiss': 'Date de naissance',
            'cp_naiss': 'Code postal de naissance',
            'ville_naiss': 'Ville de naissance',
            'mail': 'Email',
            'tel_mobile': 'Téléphone mobile',
            'tel_domicile': 'Téléphone domicile',
            'adresse_auto': 'Adresse',
            'cp_auto': 'Code postal',
            'ville_auto': 'Ville',
            'ent_id': 'ID ENT',
        }
        
        return traductions.get(champ_db, champ_db)


class FamilleEnfantEntView(CustomView, TemplateView):
    """Vue pour afficher la famille d'un enfant spécifique depuis l'ENT"""
    menu_code = "famille_enfant_ent"
    template_name = "fiche_famille/famille_enfant_ent.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enfant_ent_id = kwargs.get("enfant_ent_id", None)
        idfamille = kwargs.get("idfamille", None)

        if enfant_ent_id:
            famille_data = get_enfant_famille(enfant_ent_id)
            if famille_data:
                context['representants'] = famille_data.get('representants', [])
                context['enfant'] = famille_data.get('enfant')
                context['enfant_ent_id'] = enfant_ent_id
            else:
                context['representants'] = []
                context['enfant'] = None
                messages.add_message(self.request, messages.ERROR, "Famille de l'enfant introuvable dans l'ENT")

        if idfamille:
            context["idfamille"] = int(idfamille)

        context['page_titre'] = "Famille de l'enfant - ENT"
        return context

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Ajouter toute la famille (représentants + enfant)"""
        enfant_ent_id = kwargs.get("enfant_ent_id", None)
        idfamille = kwargs.get("idfamille", None)

        if not enfant_ent_id:
            messages.add_message(request, messages.ERROR, "Identifiant de l'enfant manquant")
            return HttpResponseRedirect(reverse_lazy("ent_liste_familles"))

        # Récupérer la famille de l'enfant
        famille_data = get_enfant_famille(enfant_ent_id)

        if not famille_data:
            messages.add_message(request, messages.ERROR, "Famille introuvable dans l'ENT")
            return HttpResponseRedirect(reverse_lazy("ent_liste_familles"))

        # Vérifier si on ajoute à une famille existante ou si on crée une nouvelle famille
        if idfamille:
            new_famille = Famille.objects.get(pk=idfamille)
        else:
            # Vérifier si la famille existe déjà en base
            enfant_obj = famille_data.get('enfant')
            existing_rattachement = Rattachement.objects.filter(
                individu__ent_id=enfant_obj.get('id_ent')
            ).first()

            if existing_rattachement:
                messages.add_message(request, messages.ERROR, "Cette famille existe déjà")
                return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={'idfamille': existing_rattachement.famille.pk}))

            # Créer une nouvelle famille
            view_instance = EntListeIndividus()
            view_instance.request = request
            new_famille = view_instance.creation_famille()

        # Ajouter les représentants
        for representant in famille_data.get('representants', []):
            view_instance = EntListeIndividus()
            view_instance.request = request
            view_instance.creation_individu_ent(representant, new_famille, 1)

        # Ajouter l'enfant
        enfant_obj = famille_data.get('enfant')
        view_instance = EntListeIndividus()
        view_instance.request = request
        view_instance.creation_individu_ent(enfant_obj, new_famille, 2)

        # Mettre à jour les infos de la famille
        new_famille.Maj_infos()

        messages.add_message(request, messages.SUCCESS, "Famille ajoutée avec succès")
        return HttpResponseRedirect(reverse_lazy("famille_resume", kwargs={'idfamille': new_famille.pk}))