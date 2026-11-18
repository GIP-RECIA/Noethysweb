# -*- coding: utf-8 -*-
"""
Tests de la couche métier du SSO ENT (resoudre_utilisateur_ent) - indépendants de tout
protocole (OIDC, CAS...) : on simule directement une identité déjà confirmée (un ent_id),
comme le ferait n'importe quel protocole une fois l'échange terminé.
"""

from django.test import TestCase

from core.models import Famille, Individu, Rattachement, Utilisateur, PortailParametre, Historique
from portail.utils.utils_ent_sso import resoudre_utilisateur_ent, tracer_connexion_sso


class TestResoudreUtilisateurEnt(TestCase):

    def _creer_famille_avec_compte(self, ent_id, categorie="famille", is_active=True):
        """Compte de connexion porté par la Famille (cas normal, type_compte="famille")."""
        utilisateur = Utilisateur.objects.create_user(username=f"parent_{ent_id}", password="x")
        utilisateur.categorie = categorie
        utilisateur.is_active = is_active
        utilisateur.save()

        famille = Famille.objects.create(nom="SSOTEST", utilisateur=utilisateur)
        individu = Individu.objects.create(nom="SSOTEST", prenom="Parent", civilite=1, ent_id=ent_id)
        Rattachement.objects.create(individu=individu, famille=famille, categorie=1, titulaire=True)
        return famille, individu, utilisateur

    def test_connexion_reussie_compte_famille(self):
        self._creer_famille_avec_compte(ent_id="ENT-SSO-1")

        utilisateur, erreur = resoudre_utilisateur_ent("ENT-SSO-1")

        self.assertIsNone(erreur)
        self.assertIsNotNone(utilisateur)
        self.assertEqual(utilisateur.categorie, "famille")

    def test_ent_id_introuvable(self):
        utilisateur, erreur = resoudre_utilisateur_ent("ENT-INCONNU")

        self.assertIsNone(utilisateur)
        self.assertIn("Aucun compte", erreur)

    def test_individu_sans_famille_avec_compte_portail(self):
        Individu.objects.create(nom="SSOTEST", prenom="SansCompte", civilite=1, ent_id="ENT-SSO-2")

        utilisateur, erreur = resoudre_utilisateur_ent("ENT-SSO-2")

        self.assertIsNone(utilisateur)
        self.assertIn("pas de compte portail", erreur)

    def test_compte_desactive(self):
        self._creer_famille_avec_compte(ent_id="ENT-SSO-3", is_active=False)

        utilisateur, erreur = resoudre_utilisateur_ent("ENT-SSO-3")

        self.assertIsNone(utilisateur)
        self.assertIn("désactivé", erreur)

    def test_mode_compte_individuel(self):
        """type_compte="individu" : le compte est porté par l'Individu, pas par la Famille."""
        PortailParametre.objects.create(code="type_compte", valeur="individu")
        utilisateur = Utilisateur.objects.create_user(username="individu_test", password="x")
        utilisateur.categorie = "individu"
        utilisateur.save()
        Individu.objects.create(nom="SSOTEST", prenom="Enfant", civilite=1, ent_id="ENT-SSO-4", utilisateur=utilisateur)

        utilisateur_connecte, erreur = resoudre_utilisateur_ent("ENT-SSO-4")

        self.assertIsNone(erreur)
        self.assertEqual(utilisateur_connecte, utilisateur)

    def test_categorie_incoherente_avec_type_compte_configure(self):
        """Cas défensif : un compte de catégorie "individu" attaché par erreur à une Famille,
        alors que le portail est configuré en mode "famille" - ne doit jamais être accepté."""
        PortailParametre.objects.create(code="type_compte", valeur="famille")
        self._creer_famille_avec_compte(ent_id="ENT-SSO-5", categorie="individu")

        utilisateur, erreur = resoudre_utilisateur_ent("ENT-SSO-5")

        self.assertIsNone(utilisateur)
        self.assertIn("n'est pas autorisé", erreur)

    def test_deux_familles_avec_compte_portail_est_ambigu(self):
        """Enfant en garde partagée, rattaché à 2 familles ayant chacune un compte portail actif -
        on refuse plutôt que de choisir au hasard laquelle connecter."""
        individu = Individu.objects.create(nom="SSOTEST", prenom="Partage", civilite=1, ent_id="ENT-SSO-6")
        for suffixe in ["A", "B"]:
            utilisateur = Utilisateur.objects.create_user(username=f"parent_ambigu_{suffixe}", password="x")
            utilisateur.categorie = "famille"
            utilisateur.save()
            famille = Famille.objects.create(nom=f"SSOTEST{suffixe}", utilisateur=utilisateur)
            Rattachement.objects.create(individu=individu, famille=famille, categorie=1, titulaire=True)

        utilisateur, erreur = resoudre_utilisateur_ent("ENT-SSO-6")

        self.assertIsNone(utilisateur)
        self.assertIn("ambiguë", erreur)

    def test_historique_trace_apres_connexion(self):
        famille, individu, utilisateur = self._creer_famille_avec_compte(ent_id="ENT-SSO-7")

        utilisateur_resolu, erreur = resoudre_utilisateur_ent("ENT-SSO-7")
        tracer_connexion_sso(utilisateur_resolu)

        self.assertTrue(Historique.objects.filter(titre="Connexion au portail (SSO ENT)", famille=famille).exists())
