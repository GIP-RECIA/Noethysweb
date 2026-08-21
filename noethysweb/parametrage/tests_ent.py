# -*- coding: utf-8 -*-
"""
Tests de l'écran "Importer une école depuis l'ENT" (ImporterEcoleEnt, zone D).

Aucun appel réseau réel : get_headers / get_school sont mockés.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import Ecole, Utilisateur
from parametrage.views.ecoles import ImporterEcoleEnt, Page as EcolePage

# Tous les écrans ENT vérifient maintenant que l'intégration est activée - simule un ENT
# actif par défaut pour tout ce module (chaque test qui vise spécifiquement le cas
# "ENT désactivé" écrase ce patch localement). Un seul point de patch (la fonction interne
# de core.utils.utils_ent), quel que soit le module qui a importé ent_est_actif.
_patch_ent_actif = patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=True))


def setUpModule():
    _patch_ent_actif.start()


def tearDownModule():
    _patch_ent_actif.stop()


def _appeler(data):
    """Construit la requête + la vue (comme Django le fait via dispatch(), qu'on
    contourne ici en appelant post() directement) et renvoie la réponse."""
    request = RequestFactory().post("/", data)
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

    vue = ImporterEcoleEnt()
    vue.request = request
    vue.kwargs = {}
    response = vue.post(request)
    if hasattr(response, "render"):
        response.render()
    return response


class TestImporterEcoleEntCasBase(TestCase):
    """Cas de base de l'écran : UAI vide, connexion impossible, UAI introuvable."""

    def test_uai_vide(self):
        with patch("parametrage.views.ecoles.get_headers", return_value={"Authorization": "Bearer test"}):
            response = _appeler({"action": "rechercher", "uai": ""})
        self.assertIn(b"Veuillez saisir un code UAI", response.content)

    def test_connexion_impossible(self):
        with patch("parametrage.views.ecoles.get_headers", return_value=None):
            response = _appeler({"action": "rechercher", "uai": "UAI999"})
        self.assertIn(b"Impossible de se connecter", response.content)

    def test_uai_introuvable(self):
        with patch("parametrage.views.ecoles.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("parametrage.views.ecoles.get_school", return_value=None):
            response = _appeler({"action": "rechercher", "uai": "UAI000"})
        self.assertIn("Aucun établissement trouvé".encode(), response.content)


class TestImporterEcoleEntReconnaissanceParNom(TestCase):
    """Le fix du jour : l'écran doit retrouver une école déjà saisie à la main (sans UAI ni
    ent_id), pas seulement par ent_id/UAI - sinon une collectivité qui avait déjà ses
    écoles avant l'intégration ENT se retrouve avec des doublons à l'import."""

    def test_avertit_si_ecole_deja_existante_par_nom_seul(self):
        Ecole.objects.create(nom="École Jean Moulin")  # saisie à la main, sans UAI ni ent_id

        with patch("parametrage.views.ecoles.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("parametrage.views.ecoles.get_school", return_value={"id": "ENT-JEANMOULIN", "name": "École Jean Moulin", "UAI": "UAI-JEANMOULIN"}):
            response = _appeler({"action": "rechercher", "uai": "UAI-JEANMOULIN"})

        self.assertIn("déjà importée".encode(), response.content)

    def test_import_reutilise_lecole_existante_par_nom_au_lieu_de_dupliquer(self):
        existante = Ecole.objects.create(nom="École Jean Moulin")

        with patch("parametrage.views.ecoles.get_school", return_value={"id": "ENT-JEANMOULIN", "name": "École Jean Moulin", "UAI": "UAI-JEANMOULIN", "city": "Ville Test"}):
            _appeler({"action": "importer", "ent_id": "ENT-JEANMOULIN"})

        self.assertEqual(Ecole.objects.filter(nom="École Jean Moulin").count(), 1, "Ne doit pas créer une deuxième fiche pour la même école.")
        existante.refresh_from_db()
        self.assertEqual(existante.uai, "UAI-JEANMOULIN", "L'école existante doit être complétée (UAI), pas dupliquée.")
        self.assertEqual(existante.ent_id, "ENT-JEANMOULIN")

    def test_import_reutilise_toujours_par_ent_id_deja_connu(self):
        """Non-régression : le cas normal (ré-actualisation d'une école déjà importée
        depuis l'ENT) doit continuer à fonctionner."""
        existante = Ecole.objects.create(nom="École Déjà Liée", uai="UAI-OLD", ent_id="ENT-DEJALIE")

        with patch("parametrage.views.ecoles.get_school", return_value={"id": "ENT-DEJALIE", "name": "École Déjà Liée", "UAI": "UAI-NEW"}):
            _appeler({"action": "importer", "ent_id": "ENT-DEJALIE"})

        self.assertEqual(Ecole.objects.filter(ent_id="ENT-DEJALIE").count(), 1)
        existante.refresh_from_db()
        self.assertEqual(existante.uai, "UAI-NEW")

    def test_import_cree_une_nouvelle_ecole_si_vraiment_aucune_correspondance(self):
        with patch("parametrage.views.ecoles.get_school", return_value={"id": "ENT-NOUVELLE", "name": "École Toute Neuve", "UAI": "UAI-NOUVELLE"}):
            _appeler({"action": "importer", "ent_id": "ENT-NOUVELLE"})

        ecole = Ecole.objects.get(ent_id="ENT-NOUVELLE")
        self.assertEqual(ecole.nom, "École Toute Neuve")


class TestImporterEcoleEntBloqueSiEntDesactive(TestCase):
    """Le bouton "Importer depuis l'ENT" et l'écran lui-même doivent disparaître/se bloquer
    quand l'ENT est désactivé dans Paramétrage - même par une URL tapée à la main."""

    def test_bouton_liste_ecoles_absent_si_ent_inactif(self):
        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            labels = [b["label"] for b in EcolePage().boutons_liste]
        self.assertEqual(labels, ["Ajouter"])

    def test_bouton_liste_ecoles_present_si_ent_actif(self):
        labels = [b["label"] for b in EcolePage().boutons_liste]
        self.assertIn("Importer depuis l'ENT", labels)

    def test_get_bloque_si_ent_inactif(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            response = ImporterEcoleEnt().get(request)
        self.assertEqual(response.status_code, 302)

    def test_post_bloque_si_ent_inactif(self):
        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            response = _appeler({"action": "rechercher", "uai": "UAI999"})
        self.assertEqual(response.status_code, 302)
