# -*- coding: utf-8 -*-
"""
Tests de l'écran "Importer une école depuis l'ENT" (ImporterEcoleEnt, zone D).

Aucun appel réseau réel : get_headers / get_school sont mockés.
"""

import uuid
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import Ecole, Utilisateur
from parametrage.views.ecoles import ImporterEcoleEnt


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
