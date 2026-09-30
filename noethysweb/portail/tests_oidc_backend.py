# -*- coding: utf-8 -*-
"""
Tests du backend OIDC (OIDCBackendEnt) - la partie propre au protocole OIDC. On ne teste jamais
un vrai échange réseau (get_token/verify_token) : on simule directement la réponse déjà décodée
de get_userinfo(), comme le ferait n'importe quel serveur OIDC une fois l'échange terminé. Le
choix du claim contenant l'identifiant ENT (OIDC_ENT_ID_CLAIM) reste à confirmer avec Edifice -
"sub" est la valeur par défaut, testée ici, mais pourrait changer.
"""

from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import Famille, Individu, Rattachement, Utilisateur, Historique
from portail.oidc_backend import OIDCBackendEnt


class TestOIDCBackendEnt(TestCase):

    def setUp(self):
        self.backend = OIDCBackendEnt()

    def _creer_famille_avec_compte(self, ent_id):
        utilisateur = Utilisateur.objects.create_user(username=f"parent_{ent_id}", password="x")
        utilisateur.categorie = "famille"
        utilisateur.save()
        famille = Famille.objects.create(nom="OIDCTEST", utilisateur=utilisateur)
        individu = Individu.objects.create(nom="OIDCTEST", prenom="Parent", civilite=1, ent_id=ent_id)
        Rattachement.objects.create(individu=individu, famille=famille, categorie=1, titulaire=True)
        return famille, utilisateur

    def test_verify_claims_accepte_si_claim_ent_id_present(self):
        self.assertTrue(self.backend.verify_claims({"sub": "ENT-1"}))

    def test_verify_claims_refuse_si_claim_absent(self):
        self.assertFalse(self.backend.verify_claims({"email": "test@example.com"}))

    def test_connexion_reussie(self):
        famille, utilisateur = self._creer_famille_avec_compte("ENT-OIDC-1")

        with patch.object(self.backend, "get_userinfo", return_value={"sub": "ENT-OIDC-1"}):
            resultat = self.backend.get_or_create_user("access_token", "id_token", {})

        self.assertEqual(resultat, utilisateur)
        self.assertTrue(Historique.objects.filter(titre="Connexion au portail (SSO ENT)", famille=famille).exists())

    def test_claim_absente_refuse_sans_planter(self):
        with patch.object(self.backend, "get_userinfo", return_value={"email": "test@example.com"}):
            resultat = self.backend.get_or_create_user("access_token", "id_token", {})

        self.assertIsNone(resultat)

    def test_ent_id_inconnu_refuse_sans_creer_de_compte(self):
        nb_utilisateurs_avant = Utilisateur.objects.count()

        with patch.object(self.backend, "get_userinfo", return_value={"sub": "ENT-INCONNU"}):
            resultat = self.backend.get_or_create_user("access_token", "id_token", {})

        self.assertIsNone(resultat)
        self.assertEqual(Utilisateur.objects.count(), nb_utilisateurs_avant)

    @override_settings(OIDC_ENT_ID_CLAIM="ent_user_id")
    def test_nom_du_claim_configurable(self):
        """Si Edifice utilise un autre nom de claim que "sub", il suffit de changer le réglage."""
        famille, utilisateur = self._creer_famille_avec_compte("ENT-OIDC-2")

        with patch.object(self.backend, "get_userinfo", return_value={"ent_user_id": "ENT-OIDC-2"}):
            resultat = self.backend.get_or_create_user("access_token", "id_token", {})

        self.assertEqual(resultat, utilisateur)
