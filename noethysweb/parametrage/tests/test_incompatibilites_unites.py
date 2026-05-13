# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime
from django.test import TestCase
from django.urls import reverse
from core.models import *
from core.tests import Classe_commune
from parametrage.forms.activites_unites_conso import Formulaire


class TestIncompatibilitesUnites(TestCase):
    """Test la synchronisation des incompatibilités d'unités"""

    def setUp(self):
        """Configuration des données de test"""
        # Création d'une structure
        self.structure = Structure.objects.create(nom="Structure test")

        # Création d'une activité
        self.activite = Activite.objects.create(
            nom="Activité test",
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2020, 12, 31),
            structure=self.structure
        )

        # Création d'un groupe
        self.groupe = Groupe.objects.create(
            nom="Groupe test",
            ordre=1,
            activite=self.activite
        )

        # Création de trois unités
        self.unite_matin = Unite.objects.create(
            nom="Matin",
            abrege="MAT",
            ordre=1,
            activite=self.activite,
            type="Unitaire",
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2020, 12, 31)
        )

        self.unite_journee = Unite.objects.create(
            nom="Journée",
            abrege="JRN",
            ordre=2,
            activite=self.activite,
            type="Unitaire",
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2020, 12, 31)
        )

        self.unite_sieste = Unite.objects.create(
            nom="Sieste",
            abrege="SIE",
            ordre=3,
            activite=self.activite,
            type="Unitaire",
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2020, 12, 31)
        )

    def test_sync_incompatibilites_ajout(self):
        """Test que l'ajout d'incompatibilité est bien synchronisé dans les deux sens"""
        # Configuration initiale : aucune incompatibilité
        self.assertEqual(self.unite_matin.incompatibilites.count(), 0)
        self.assertEqual(self.unite_journee.incompatibilites.count(), 0)

        # Simulation du formulaire avec incompatibilité Matin -> Journée
        form_data = {
            'nom': 'Matin modifié',
            'abrege': 'MAT',
            'ordre': 1,
            'type': 'Unitaire',
            'date_debut': '2020-01-01',
            'date_fin': '2020-12-31',
            'validite_type': 'ILLIMITEE',  # Champ requis
            'groupes_type': 'TOUS',  # Champ requis
            'categories_tarifs_type': 'TOUS',  # Champ requis
            'activite': self.activite.pk,  # Champ requis
            'incompatibilites': [self.unite_journee.pk],  # Matin incompatible avec Journée
        }

        form = Formulaire(data=form_data, instance=self.unite_matin, idactivite=self.activite.pk)
        self.assertTrue(form.is_valid())
        
        # Sauvegarde avec la méthode save() personnalisée
        instance = form.save()
        
        # Vérification que l'incompatibilité est bidirectionnelle
        self.assertIn(self.unite_journee, instance.incompatibilites.all())
        self.assertIn(instance, self.unite_journee.incompatibilites.all())
        
        # Vérification que la sieste n'est pas affectée
        self.assertNotIn(self.unite_sieste, instance.incompatibilites.all())
        self.assertNotIn(instance, self.unite_sieste.incompatibilites.all())

    def test_sync_incompatibilites_suppression(self):
        """Test que la suppression d'incompatibilité est bien synchronisée dans les deux sens"""
        # Configuration initiale : Matin incompatible avec Journée et Sieste
        # On utilise le formulaire pour bénéficier de la synchronisation bidirectionnelle
        form_data_init = {
            'nom': 'Matin',
            'abrege': 'MAT',
            'ordre': 1,
            'type': 'Unitaire',
            'date_debut': '2020-01-01',
            'date_fin': '2020-12-31',
            'validite_type': 'ILLIMITEE',  # Champ requis
            'groupes_type': 'TOUS',  # Champ requis
            'categories_tarifs_type': 'TOUS',  # Champ requis
            'activite': self.activite.pk,  # Champ requis
            'incompatibilites': [self.unite_journee.pk, self.unite_sieste.pk],  # Matin incompatible avec Journée et Sieste
        }
        
        form_init = Formulaire(data=form_data_init, instance=self.unite_matin, idactivite=self.activite.pk)
        self.assertTrue(form_init.is_valid())
        form_init.save()

        # Vérification de l'état initial bidirectionnel (grâce à la synchronisation du formulaire)
        self.assertIn(self.unite_journee, self.unite_matin.incompatibilites.all())
        self.assertIn(self.unite_sieste, self.unite_matin.incompatibilites.all())
        self.assertIn(self.unite_matin, self.unite_journee.incompatibilites.all())
        self.assertIn(self.unite_matin, self.unite_sieste.incompatibilites.all())
        
        # Simulation du formulaire avec seulement Journée comme incompatibilité
        form_data = {
            'nom': 'Matin modifié',
            'abrege': 'MAT',
            'ordre': 1,
            'type': 'Unitaire',
            'date_debut': '2020-01-01',
            'date_fin': '2020-12-31',
            'validite_type': 'ILLIMITEE',  # Champ requis
            'groupes_type': 'TOUS',  # Champ requis
            'categories_tarifs_type': 'TOUS',  # Champ requis
            'activite': self.activite.pk,  # Champ requis
            'incompatibilites': [self.unite_journee.pk],  # Seulement Journée
        }
        
        form = Formulaire(data=form_data, instance=self.unite_matin, idactivite=self.activite.pk)
        self.assertTrue(form.is_valid())
        
        # Sauvegarde avec la méthode save() personnalisée
        instance = form.save()
        
        # Vérification que l'incompatibilité avec Journée est conservée
        self.assertIn(self.unite_journee, instance.incompatibilites.all())
        self.assertIn(instance, self.unite_journee.incompatibilites.all())
        
        # Vérification que l'incompatibilité avec Sieste est supprimée dans les deux sens
        self.assertNotIn(self.unite_sieste, instance.incompatibilites.all())
        self.assertNotIn(instance, self.unite_sieste.incompatibilites.all())
    
    def test_sync_incompatibilites_avec_code_commente(self):
        """Test qui démontre le problème quand les méthodes save() et _sync_incompatibilites() n'existent pas"""
        # Configuration initiale : aucune incompatibilité
        self.assertEqual(self.unite_matin.incompatibilites.count(), 0)
        self.assertEqual(self.unite_journee.incompatibilites.count(), 0)
        
        # Simulation du formulaire avec incompatibilité Matin -> Journée
        form_data = {
            'nom': 'Matin modifié',
            'abrege': 'MAT',
            'ordre': 1,
            'type': 'Unitaire',
            'date_debut': '2020-01-01',
            'date_fin': '2020-12-31',
            'validite_type': 'ILLIMITEE',  # Champ requis
            'groupes_type': 'TOUS',  # Champ requis
            'categories_tarifs_type': 'TOUS',  # Champ requis
            'activite': self.activite.pk,  # Champ requis
            'incompatibilites': [self.unite_journee.pk],  # Matin incompatible avec Journée
        }
        
        form = Formulaire(data=form_data, instance=self.unite_matin, idactivite=self.activite.pk)
        self.assertTrue(form.is_valid())
        
        # Sauvegarde avec la méthode save() par défaut (méthodes commentées)
        instance = form.save()
        
        # Avec le code commenté, l'incompatibilité n'est pas bidirectionnelle
        # Ce test va échouer si les méthodes sont commentées
        self.assertIn(self.unite_journee, instance.incompatibilites.all(), 
                     "L'incompatibilité devrait être enregistrée depuis Matin vers Journée")
        
        # CETTE ASSERTION ÉCHOUERA SI LE CODE EST COMMENTÉ :
        self.assertIn(instance, self.unite_journee.incompatibilites.all(), 
                     "L'incompatibilité devrait être synchronisée dans l'autre sens (Journée vers Matin)")
    
    def test_sync_incompatibilites_multiple(self):
        """Test la synchronisation avec plusieurs incompatibilités"""
        # Configuration : Matin incompatible avec Journée et Sieste
        form_data = {
            'nom': 'Matin',
            'abrege': 'MAT',
            'ordre': 1,
            'type': 'Unitaire',
            'date_debut': '2020-01-01',
            'date_fin': '2020-12-31',
            'validite_type': 'ILLIMITEE',  # Champ requis
            'groupes_type': 'TOUS',  # Champ requis
            'categories_tarifs_type': 'TOUS',  # Champ requis
            'activite': self.activite.pk,  # Champ requis
            'incompatibilites': [self.unite_journee.pk, self.unite_sieste.pk],
        }
        
        form = Formulaire(data=form_data, instance=self.unite_matin, idactivite=self.activite.pk)
        self.assertTrue(form.is_valid())
        
        instance = form.save()
        
        # Vérification que toutes les incompatibilités sont bidirectionnelles
        self.assertIn(self.unite_journee, instance.incompatibilites.all())
        self.assertIn(self.unite_sieste, instance.incompatibilites.all())
        self.assertIn(instance, self.unite_journee.incompatibilites.all())
        self.assertIn(instance, self.unite_sieste.incompatibilites.all())
        
        # Modification : ne garder que Journée
        form_data['incompatibilites'] = [self.unite_journee.pk]
        form = Formulaire(data=form_data, instance=instance, idactivite=self.activite.pk)
        self.assertTrue(form.is_valid())
        
        instance = form.save()
        
        # Vérification que seule l'incompatibilité avec Journée reste
        self.assertIn(self.unite_journee, instance.incompatibilites.all())
        self.assertIn(instance, self.unite_journee.incompatibilites.all())
        
        # Vérification que l'incompatibilité avec Sieste est supprimée
        self.assertNotIn(self.unite_sieste, instance.incompatibilites.all())
        self.assertNotIn(instance, self.unite_sieste.incompatibilites.all())
