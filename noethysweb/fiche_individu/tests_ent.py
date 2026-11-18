# -*- coding: utf-8 -*-
"""
Tests de la logique de corroboration ENT - liaison individuelle (LierCompteEnt).

IMPORTANT : ces tests vérifient le comportement ATTENDU (règles métier validées),
pas forcément le comportement actuel du code. Un test rouge signale un écart du
code par rapport à la règle, pas une erreur du test.

Aucun appel réseau réel : search_by_name / get_headers sont mockés.
"""

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, Mock

import requests
from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

# Tous les écrans ENT vérifient maintenant que l'intégration est activée - simule un ENT
# actif par défaut pour tout ce module (chaque test qui vise spécifiquement le cas
# "ENT désactivé" écrase ce patch localement). Un seul point de patch (la fonction interne
# de core.utils.utils_ent), quel que soit le module qui a importé ent_est_actif.
_patch_ent_actif = patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=True))


def setUpModule():
    _patch_ent_actif.start()


def tearDownModule():
    _patch_ent_actif.stop()
from django.contrib.messages import get_messages
from django.utils import timezone

from core.models import Activite, Assurance, Assureur, CategorieTarif, Classe, Ecole, Famille, Groupe, Historique, Individu, Inscription, Organisateur, Rattachement, Scolarite, Structure, Utilisateur
from core.utils.utils_ent import get_user_ou_introuvable
from fiche_individu.views.individu_ent import LierCompteEnt, SynchroniserIndividu, Get_lignes_comparaison, Appliquer_sync_ecole_classe, Get_scolarite_actuelle
from fiche_famille.views.famille_ent import _get_annee_scolaire_par_defaut
from fiche_individu.views.individu_assurances import ReattribuerAssurance
from fiche_individu.views.individu_inscriptions import Ajouter, ReattribuerInscription


def _resultat_eleve(ent_id, nom, prenom, birth=None, parents=None, ecole=None, classe=None, ecole_uai=None, ecole_ent_id=None):
    """Fabrique un résultat ENT au format admin/list pour un élève."""
    resultat = {
        "id": ent_id,
        "type": "Student",
        "firstName": prenom,
        "lastName": nom,
        "birthDate": birth,
        "parents": list(parents or []),
    }
    if ecole:
        resultat["structures"] = [{"name": ecole, "uai": ecole_uai, "id": ecole_ent_id}]
    if classe:
        resultat["allClasses"] = [{"name": classe}]
    return resultat


def _est_proposable(membre):
    """La case 'Lier aussi X' est-elle affichée pour ce membre ? Lit le champ canonique
    "proposable" calculé par la vue - c'est la même source que le template
    (individu_ent_lier.html), pour que test et écran ne puissent pas diverger."""
    return bool(membre.get("proposable"))


class TestCorroborationLiaisonIndividuelle(TestCase):

    def setUp(self):
        self.vue = LierCompteEnt()
        self.famille = Famille.objects.create(nom="FAMTEST")
        self.enfant = Individu.objects.create(nom="FAMTEST", prenom="Enfant", civilite=4)
        self.parent = Individu.objects.create(nom="FAMTEST", prenom="Parent", civilite=1)
        Rattachement.objects.create(individu=self.enfant, famille=self.famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=self.parent, famille=self.famille, categorie=1, titulaire=True)

    def _rechercher(self, reponse_ent, individu=None, famille=None):
        individu = individu or self.enfant
        famille = famille or self.famille
        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            resultats, erreur = self.vue._rechercher(individu.nom, individu.prenom, famille.pk, individu.pk)
        self.assertIsNone(erreur)
        return resultats

    def _requete_post(self, data):
        request = RequestFactory().post("/", data)
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        return request

    # ------------------------------------------------- panne ENT vs absence de résultat

    def test_panne_en_cours_de_recherche_nest_pas_annoncee_comme_absence_de_fiche(self):
        """Une panne ENT survenant APRÈS l'obtention du token (token encore valide en cache,
        mais l'appel échoue : timeout, 500, coupure) doit produire un message de connexion.
        L'annoncer comme "cet individu n'existe peut-être pas" est un diagnostic faux, qui
        pousse l'agent à conclure à tort qu'il n'y a pas de compte à lier."""
        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=None):
            resultats, erreur = self.vue._rechercher(
                self.enfant.nom, self.enfant.prenom, self.famille.pk, self.enfant.pk,
            )

        self.assertIsNone(resultats)
        self.assertIn("connexion", erreur.lower())
        self.assertNotIn(
            "n'y existe peut-être pas", erreur,
            "Une panne de connexion est annoncée comme une absence de fiche dans l'ENT.",
        )

    def test_aucun_resultat_reste_bien_annonce_comme_tel(self):
        """Non-régression du test ci-dessus : une vraie réponse vide de l'ENT (liste vide,
        pas None) doit continuer à dire "aucun résultat", pas "panne"."""
        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=[]):
            resultats, erreur = self.vue._rechercher(
                self.enfant.nom, self.enfant.prenom, self.famille.pk, self.enfant.pk,
            )

        self.assertIsNone(resultats)
        self.assertIn("Aucun résultat", erreur)

    # ------------------------------------------------------------------ règle 1

    def test_regle1_parent_dont_le_compte_ent_est_deja_pris_nest_pas_propose(self):
        """Règle 1 : un parent dont le compte ENT candidat est déjà utilisé par un
        AUTRE individu Noethys ne doit jamais être proposé comme correspondance."""
        # Un autre individu, sans rapport, détient déjà le compte ENT du parent
        Individu.objects.create(nom="AUTRE", prenom="Individu", civilite=1, ent_id="ENT-P")

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        membre = resultats[0]["membres_enrichis"][0]
        self.assertFalse(
            _est_proposable(membre),
            "Le parent est proposé (case à cocher) alors que son compte ENT candidat "
            "est déjà utilisé par un autre individu Noethys.",
        )

    # ------------------------------------------------------------------ règle 2

    def test_regle2_lie_a_autre_compte_ne_compte_pas_et_est_signale_distinctement(self):
        """Règle 2 : un individu déjà lié à un AUTRE compte ENT ne compte pas comme
        preuve, et le signalement est distinct de 'aucune correspondance'."""
        self.parent.ent_id = "UN-AUTRE-COMPTE"
        self.parent.save()

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        membre = resultat["membres_enrichis"][0]

        self.assertTrue(membre["lie_a_autre_compte"])
        self.assertFalse(membre["deja_lie"])
        self.assertFalse(_est_proposable(membre))
        # Ne compte pas comme preuve
        self.assertTrue(resultat["aucune_corroboration"])
        # Signalé distinctement du cas générique "aucune correspondance"
        self.assertIn("autre compte", resultat["message_avertissement"])
        self.assertNotEqual(
            resultat["message_avertissement"],
            "Aucun parent/enfant ne correspond à un membre de cette famille sur Noethys.",
        )

    # ------------------------------------------------------------------ règle 3

    def test_regle3_nom_corrobore_mais_date_contradictoire_rejete(self):
        """Règle 3 : nom d'un parent qui corrobore + date de naissance connue des deux
        côtés qui se contredisent => corroboration rejetée (probable homonyme)."""
        self.enfant.date_naiss = date(2010, 1, 1)
        self.enfant.save()

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        self.assertIs(resultat["date_coherente"], False)
        self.assertTrue(
            resultat["aucune_corroboration"],
            "La corroboration par le nom est acceptée alors que la date de naissance la contredit.",
        )
        self.assertIn("date de naissance", resultat["message_avertissement"])

    # ------------------------------------------------------------------ règle 4

    def test_regle4_date_absente_ne_penalise_pas_le_nom(self):
        """Règle 4 : une date absente d'un côté (ENT ou Noethys) ne doit pas pénaliser
        une corroboration par nom qui fonctionne."""
        parents = [{"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"}]

        # Cas A : date absente côté ENT
        self.enfant.date_naiss = date(2010, 1, 1)
        self.enfant.save()
        resultats = self._rechercher([_resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth=None, parents=parents)])
        self.assertIsNone(resultats[0]["date_coherente"])
        self.assertFalse(resultats[0]["aucune_corroboration"])

        # Cas B : date absente côté Noethys
        self.enfant.date_naiss = None
        self.enfant.save()
        resultats = self._rechercher([_resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=parents)])
        self.assertIsNone(resultats[0]["date_coherente"])
        self.assertFalse(resultats[0]["aucune_corroboration"])

    # ------------------------------------------------------------------ règle 5

    def test_regle5_date_seule_suffit_a_corroborer(self):
        """Règle 5 : une date de naissance qui correspond peut corroborer à elle seule,
        même sans corroboration par le nom."""
        self.enfant.date_naiss = date(2006, 10, 8)
        self.enfant.save()

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
                # Parent ENT qui ne correspond à personne dans la famille Noethys
                {"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"},
            ]),
        ])
        resultat = resultats[0]
        self.assertIs(resultat["date_coherente"], True)
        self.assertFalse(
            resultat["aucune_corroboration"],
            "La date qui correspond exactement devrait suffire à corroborer.",
        )

    def test_regle5b_date_seule_corrobore_mais_avertit(self):
        """Règle 5 (suite) : la date seule corrobore (règle 5 inchangée), mais comme c'est
        la preuve la plus faible et que rien à l'écran ne la met en évidence, ce cas doit
        être signalé à l'agent au lieu d'être lié en silence."""
        self.enfant.date_naiss = date(2006, 10, 8)
        self.enfant.save()

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
                {"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"},
            ]),
        ])
        resultat = resultats[0]
        # Toujours corroboré (règle 5) : on lie, on ne bloque pas
        self.assertFalse(resultat["aucune_corroboration"])
        # ... mais explicitement signalé comme reposant sur la seule date
        self.assertTrue(resultat["corrobore_par_date_seule"])
        self.assertIn("date de naissance", resultat["message_avertissement"])

    def test_regle5c_corroboration_par_nom_nest_pas_signalee_comme_date_seule(self):
        """Le nouveau signalement ne doit se déclencher QUE sans corroboration par le nom -
        un cas nom + date ne doit pas se mettre à avertir (pas de régression sur le flux
        normal, qui doit rester sans popup)."""
        self.enfant.date_naiss = date(2006, 10, 8)
        self.enfant.save()

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        self.assertFalse(resultat["aucune_corroboration"])
        self.assertFalse(resultat["corrobore_par_date_seule"])

    # ------------------------------------------------- école/classe (3e critère)

    def _creer_scolarite_noethys(self, individu, ecole_nom, uai=None, ent_id=None, classe_nom=None):
        ecole = Ecole.objects.create(nom=ecole_nom, uai=uai, ent_id=ent_id)
        classe = None
        if classe_nom:
            classe = Classe.objects.create(ecole=ecole, nom=classe_nom, date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))
        Scolarite.objects.create(individu=individu, ecole=ecole, classe=classe, date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))
        return ecole

    def test_ecole_classe_seule_suffit_a_corroborer(self):
        """École + classe qui correspondent peuvent corroborer à elles seules, même sans
        aucun nom de parent ni date de naissance qui matche."""
        self._creer_scolarite_noethys(self.enfant, "École Test", uai="UAI999", ent_id="ENT-ECOLE-1", classe_nom="CE2 A")

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", ecole="École Test", ecole_uai="UAI999", ecole_ent_id="ENT-ECOLE-1", classe="CE2 A", parents=[
                {"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"},
            ]),
        ])
        resultat = resultats[0]
        self.assertIs(resultat["ecole_coherente"], True)
        self.assertFalse(
            resultat["aucune_corroboration"],
            "École + classe qui correspondent devraient suffire à corroborer.",
        )
        self.assertTrue(resultat["corrobore_par_ecole_seule"])
        self.assertIn("école et la classe", resultat["message_avertissement"])

    def test_ecole_incoherente_ne_bloque_jamais_une_corroboration_par_nom(self):
        """Contrairement à la date, une école/classe qui NE correspond PAS ne doit jamais
        faire échouer une corroboration par le nom - juste un avertissement doux, non
        bloquant (la scolarité Noethys peut simplement être celle de l'an dernier)."""
        self._creer_scolarite_noethys(self.enfant, "Ancienne École", uai="UAI111", ent_id="ENT-ANCIENNE", classe_nom="CM1 B")

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", ecole="Nouvelle École", ecole_uai="UAI222", ecole_ent_id="ENT-NOUVELLE", classe="CM2 A", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        # L'école Noethys "Nouvelle École" n'existe même pas -> _trouver_ecole renvoie None
        # -> ecole_coherente reste None (rien à comparer), le nom seul suffit déjà ici.
        self.assertFalse(resultat["aucune_corroboration"], "Le nom corrobore, la liaison ne doit pas être bloquée.")

    def test_ecole_incoherente_avec_ecole_connue_ne_bloque_pas_non_plus(self):
        """Même chose, mais cette fois l'école ENT est bien connue de Noethys (juste
        différente de celle enregistrée pour cet enfant) - la contradiction est donc
        détectée (ecole_coherente=False), mais ne bloque toujours pas."""
        self._creer_scolarite_noethys(self.enfant, "Ancienne École", uai="UAI111", ent_id="ENT-ANCIENNE", classe_nom="CM1 B")
        Ecole.objects.create(nom="Nouvelle École", uai="UAI222", ent_id="ENT-NOUVELLE")

        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", ecole="Nouvelle École", ecole_uai="UAI222", ecole_ent_id="ENT-NOUVELLE", classe="CM2 A", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        self.assertIs(resultat["ecole_coherente"], False)
        self.assertFalse(
            resultat["aucune_corroboration"],
            "Une école/classe incohérente a bloqué une corroboration par le nom - elle ne devrait jamais avoir ce pouvoir.",
        )
        self.assertTrue(
            resultat["ecole_incoherente_info"],
            "L'incohérence école/classe devrait au moins être signalée (avertissement doux, non bloquant).",
        )

    def test_ecole_absente_ne_penalise_pas(self):
        """Non-régression : si Noethys n'a aucune Scolarité enregistrée pour l'enfant, ou si
        l'ENT ne fournit pas d'école, ecole_coherente reste None - le nom seul suffit comme
        avant, l'ajout du 3e critère ne doit rien casser du flux normal."""
        resultats = self._rechercher([
            _resultat_eleve("ENT-E", "FAMTEST", "Enfant", parents=[
                {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
            ]),
        ])
        resultat = resultats[0]
        self.assertIsNone(resultat["ecole_coherente"])
        self.assertFalse(resultat["aucune_corroboration"])
        self.assertFalse(resultat["corrobore_par_ecole_seule"])

    # ------------------------------------------------------------------ règle 7

    def test_regle7_enfant_multi_familles_cherche_sur_toutes_les_familles(self):
        """Règle 7 : un enfant rattaché à 2 familles (garde partagée) doit être
        corroboré par les membres de TOUTES ses familles, pas seulement celle passée
        en paramètre."""
        famille2 = Famille.objects.create(nom="FAMTEST2")
        parent2 = Individu.objects.create(nom="FAMTEST", prenom="Maman", civilite=3)
        Rattachement.objects.create(individu=parent2, famille=famille2, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=self.enfant, famille=famille2, categorie=2, titulaire=False)

        # L'ENT ne donne QUE le parent de la famille 2, et on lance la recherche
        # depuis la famille 1
        resultats = self._rechercher(
            [
                _resultat_eleve("ENT-E", "FAMTEST", "Enfant", parents=[
                    {"firstName": "Maman", "lastName": "FAMTEST", "id": "ENT-M"},
                ]),
            ],
            famille=self.famille,  # famille 1
        )
        membre = resultats[0]["membres_enrichis"][0]
        self.assertEqual(
            membre["individu_correspondant"], parent2,
            "Le parent de l'autre famille de l'enfant n'a pas été retrouvé.",
        )
        self.assertFalse(resultats[0]["aucune_corroboration"])

    # ------------------------------------------------------------------ règle 8

    def test_regle8a_ent_id_existant_du_principal_jamais_ecrase_via_post_direct(self):
        """Règle 8 : un ent_id déjà existant sur l'individu principal ne doit jamais
        être écrasé, même par une requête directe (protection serveur)."""
        self.enfant.ent_id = "ANCIEN-COMPTE"
        self.enfant.save()

        request = self._requete_post({"action": "lier", "ent_id": "NOUVEAU-COMPTE"})
        self.vue.request = request
        self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
        self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.enfant.refresh_from_db()
        self.assertEqual(
            self.enfant.ent_id, "ANCIEN-COMPTE",
            "L'ent_id existant de l'individu principal a été écrasé par un POST direct.",
        )

    def test_regle8b_ent_id_existant_dun_parent_jamais_ecrase(self):
        """Règle 8 (parents cochés) : un parent qui a déjà un ent_id ne doit pas être
        écrasé par la liaison groupée, même si la case est envoyée directement."""
        self.parent.ent_id = "ANCIEN-COMPTE-PARENT"
        self.parent.save()

        request = self._requete_post({
            "action": "lier",
            "ent_id": "ENT-E",
            f"parent_lier_{self.parent.pk}": "NOUVEAU-COMPTE-PARENT",
        })
        self.vue.request = request
        self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
        # post() action='lier' recalcule désormais la corroboration (traçabilité) - mock
        # nécessaire même si ce test ne porte pas là-dessus.
        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=[]):
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.parent.refresh_from_db()
        self.assertEqual(
            self.parent.ent_id, "ANCIEN-COMPTE-PARENT",
            "L'ent_id existant du parent a été écrasé.",
        )

    # ------------------------------------------------------- traçabilité (Historique)

    def test_historique_liaison_forcee_sans_corroboration_est_tracee(self):
        """Une liaison confirmée malgré 'aucune_corroboration' doit être tracée dans
        l'historique Noethys (demande de l'équipe : sécurité/aspects légaux), avec
        l'agent, la personne liée et la raison précise."""
        agent = Utilisateur.objects.create_user(username="agent_test_1")
        reponse_ent = [_resultat_eleve("ENT-E", "FAMTEST", "Enfant")]  # aucun parent -> aucune corroboration

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E"})
            request.user = agent
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        logs = Historique.objects.filter(individu_id=self.enfant.pk)
        self.assertEqual(logs.count(), 1, "La liaison forcée sans corroboration n'a pas été tracée.")
        log = logs.first()
        self.assertEqual(log.utilisateur, agent)
        self.assertEqual(log.famille_id, self.famille.pk)
        self.assertIn("forcée", log.titre.lower())
        self.assertIn("aucune correspondance", log.detail)
        self.assertIn(str(self.enfant), log.detail)

    def test_historique_liaison_forcee_par_date_seule_est_tracee(self):
        """Même chemin UI (popup 'lier quand même') pour le cas 'preuve la plus faible' -
        date seule, sans nom - doit aussi être tracé, avec la bonne raison."""
        agent = Utilisateur.objects.create_user(username="agent_test_2")
        self.enfant.date_naiss = date(2006, 10, 8)
        self.enfant.save()
        reponse_ent = [_resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
            {"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"},
        ])]

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E"})
            request.user = agent
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        log = Historique.objects.filter(individu_id=self.enfant.pk).first()
        self.assertIsNotNone(log, "La liaison forcée par la date seule n'a pas été tracée.")
        self.assertIn("date de naissance seule", log.detail)

    def test_historique_liaison_forcee_par_ecole_seule_est_tracee(self):
        """Même chemin UI (popup 'lier quand même') pour le cas école/classe seule -
        doit aussi être tracé, avec la bonne raison (pas juste 'aucune correspondance')."""
        agent = Utilisateur.objects.create_user(username="agent_test_ecole")
        self._creer_scolarite_noethys(self.enfant, "École Test", uai="UAI999", ent_id="ENT-ECOLE-1", classe_nom="CE2 A")
        reponse_ent = [_resultat_eleve(
            "ENT-E", "FAMTEST", "Enfant", ecole="École Test", ecole_uai="UAI999", ecole_ent_id="ENT-ECOLE-1", classe="CE2 A",
            parents=[{"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"}],
        )]

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E"})
            request.user = agent
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        log = Historique.objects.filter(individu_id=self.enfant.pk).first()
        self.assertIsNotNone(log, "La liaison forcée par l'école/classe seule n'a pas été tracée.")
        self.assertIn("école et classe seules", log.detail)

    def test_historique_liaison_normale_nest_pas_tracee(self):
        """Non-régression : une liaison normale (nom + date qui corroborent) ne doit pas
        créer de trace - la traçabilité ne concerne que les liaisons forcées."""
        self.enfant.date_naiss = date(2006, 10, 8)
        self.enfant.save()
        reponse_ent = [_resultat_eleve("ENT-E", "FAMTEST", "Enfant", birth="2006-10-08", parents=[
            {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
        ])]

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E"})
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.assertEqual(
            Historique.objects.filter(individu_id=self.enfant.pk).count(), 0,
            "Une liaison normale (bien corroborée) a été tracée à tort comme forcée.",
        )

    # ------------------------------------------------- trace ent_lie_par / ent_lie_le

    def test_ent_lie_par_enregistre_lagent_sur_liaison_individuelle(self):
        """Toute liaison faite sur l'écran individuel (forcée ou pas) doit garder une
        trace de l'agent qui l'a posée et de la date, directement sur la fiche."""
        agent = Utilisateur.objects.create_user(username="agent_qui_lie")
        avant = timezone.now()

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=[_resultat_eleve("ENT-E", "FAMTEST", "Enfant")]):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E"})
            request.user = agent
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.enfant.refresh_from_db()
        self.assertEqual(self.enfant.ent_lie_par, "agent_qui_lie")
        self.assertIsNotNone(self.enfant.ent_lie_le)
        self.assertGreaterEqual(self.enfant.ent_lie_le, avant)

    def test_ent_lie_par_enregistre_aussi_pour_un_parent_coche(self):
        """Un parent lié en même temps que l'enfant (case cochée) garde lui aussi sa
        propre trace qui/quand, pas seulement l'enfant principal."""
        agent = Utilisateur.objects.create_user(username="agent_qui_lie_2")

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=[
                 _resultat_eleve("ENT-E", "FAMTEST", "Enfant", parents=[
                     {"firstName": "Parent", "lastName": "FAMTEST", "id": "ENT-P"},
                 ]),
             ]):
            request = self._requete_post({"action": "lier", "ent_id": "ENT-E", f"parent_lier_{self.parent.pk}": "ENT-P"})
            request.user = agent
            self.vue.request = request
            self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
            self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.parent.refresh_from_db()
        self.assertEqual(self.parent.ent_lie_par, "agent_qui_lie_2")
        self.assertIsNotNone(self.parent.ent_lie_le)

    # ------------------------------------------------------------------- délier

    def test_delier_vide_ent_id_et_les_champs_de_trace(self):
        """Délier une fiche doit vider ent_id ET ent_lie_par/ent_lie_le - ils ne
        veulent plus rien dire une fois le lien cassé."""
        agent = Utilisateur.objects.create_user(username="agent_qui_lie_3")
        self.enfant.ent_id = "ANCIEN-COMPTE"
        self.enfant.ent_lie_par = "un_autre_agent"
        self.enfant.ent_lie_le = timezone.now()
        self.enfant.save()

        request = self._requete_post({"action": "delier"})
        request.user = agent
        self.vue.request = request
        self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
        self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.enfant.refresh_from_db()
        self.assertIsNone(self.enfant.ent_id)
        self.assertIsNone(self.enfant.ent_lie_par)
        self.assertIsNone(self.enfant.ent_lie_le)

    def test_delier_trace_lancien_lien_dans_lhistorique(self):
        """Avant d'effacer le lien, il faut garder une trace de ce qu'il y avait -
        sinon on perd l'info "il y avait un lien, lequel, posé par qui" au moment
        précis où on la supprime."""
        agent = Utilisateur.objects.create_user(username="agent_qui_delie")
        self.enfant.ent_id = "ANCIEN-COMPTE-XYZ"
        self.enfant.ent_lie_par = "premier_agent"
        self.enfant.ent_lie_le = timezone.now()
        self.enfant.save()

        request = self._requete_post({"action": "delier"})
        request.user = agent
        self.vue.request = request
        self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
        self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        log = Historique.objects.filter(individu_id=self.enfant.pk, titre__icontains="déliée").first()
        self.assertIsNotNone(log, "Aucune trace créée pour l'action de déliaison.")
        self.assertEqual(log.utilisateur, agent)
        self.assertIn("ANCIEN-COMPTE-XYZ", log.detail)
        self.assertIn("premier_agent", log.detail)

    def test_delier_sans_lien_existant_ne_plante_pas(self):
        """Non-régression : délier une fiche déjà non liée ne doit pas planter, ni
        créer de trace inutile - juste un message informatif."""
        request = self._requete_post({"action": "delier"})
        request.user = Utilisateur.objects.create_user(username="agent_test_delier_vide")
        self.vue.request = request
        self.vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.enfant.pk}
        self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.enfant.refresh_from_db()
        self.assertIsNone(self.enfant.ent_id)
        self.assertEqual(Historique.objects.filter(individu_id=self.enfant.pk).count(), 0)


class TestCorroborationSymetrieEtAccents(TestCase):
    """Deux cas du moteur de corroboration (LierCompteEnt._rechercher) jamais testés
    directement : la symétrie (chercher depuis un parent regarde ses enfants côté ENT,
    pas ses "parents" qui n'existent pas pour un adulte), et l'insensibilité aux accents/
    casse dans la comparaison des noms de famille."""

    def setUp(self):
        self.vue = LierCompteEnt()

    def _rechercher(self, reponse_ent, individu, famille):
        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", return_value=reponse_ent):
            resultats, erreur = self.vue._rechercher(individu.nom, individu.prenom, famille.pk, individu.pk)
        self.assertIsNone(erreur)
        return resultats

    def test_symetrie_recherche_depuis_un_parent_regarde_ses_enfants(self):
        famille = Famille.objects.create(nom="FAMSYM")
        enfant = Individu.objects.create(nom="FAMSYM", prenom="Enfant", civilite=4)
        parent = Individu.objects.create(nom="FAMSYM", prenom="Parent", civilite=1)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        resultat_relative = {
            "id": "ENT-PARENT-SYM", "type": "Relative", "firstName": "Parent", "lastName": "FAMSYM",
            "children": [{"firstName": "Enfant", "lastName": "FAMSYM", "id": "ENT-ENFANT-SYM"}],
        }
        resultats = self._rechercher([resultat_relative], individu=parent, famille=famille)

        self.assertEqual(resultats[0]["membres_label"], "Enfants")
        membre = resultats[0]["membres_enrichis"][0]
        self.assertEqual(membre["individu_correspondant"], enfant)
        self.assertTrue(resultats[0]["nom_corrobore"])

    def test_comparaison_noms_insensible_aux_accents_et_a_la_casse(self):
        famille = Famille.objects.create(nom="FAMACCENT")
        enfant = Individu.objects.create(nom="GAUTHIER", prenom="Chloé", civilite=4)
        parent = Individu.objects.create(nom="GAUTHIER", prenom="François", civilite=1)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        resultat = _resultat_eleve("ENT-ACCENT", "GAUTHIER", "Chloe", parents=[
            {"firstName": "FRANCOIS", "lastName": "gauthier", "id": "ENT-PARENT-ACCENT"},
        ])
        resultats = self._rechercher([resultat], individu=enfant, famille=famille)

        membre = resultats[0]["membres_enrichis"][0]
        self.assertEqual(
            membre["individu_correspondant"], parent,
            "La comparaison des noms devrait être insensible aux accents et à la casse.",
        )


class TestReattributionAssurance(TestCase):
    """Le bouton "Réattribuer à une autre famille" pour une assurance - même outil que pour
    les prestations, mais pour une donnée qui n'a aucun lien à une prestation précise (une
    assurance existe toute seule). Sert à corriger le cas d'un enfant partagé après une
    séparation, resté ambigu faute de titulaire clair."""

    def _reattribuer(self, assurance, famille_origine, famille_cible, idindividu):
        request = RequestFactory().post("/", {"idfamille_cible": famille_cible.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = ReattribuerAssurance()
        vue.request = request
        vue.kwargs = {"idfamille": famille_origine.pk, "idindividu": idindividu, "pk": assurance.pk}
        vue.post(request)

    def test_reattribution_deplace_lassurance_vers_la_famille_cible(self):
        famille_origine = Famille.objects.create(nom="ASSUR ORIGINE")
        famille_cible = Famille.objects.create(nom="ASSUR CIBLE")
        enfant = Individu.objects.create(nom="ASSURE", prenom="Enfant", civilite=4)
        # Rattaché aux deux familles (enfant partagé) - condition nécessaire pour que la
        # réattribution soit autorisée vers cette famille cible précisément.
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        assureur = Assureur.objects.create(nom="MAIF")
        assurance = Assurance.objects.create(
            individu=enfant, famille=famille_origine, assureur=assureur,
            num_contrat="CTR123", date_debut=date(2026, 9, 1),
        )

        self._reattribuer(assurance, famille_origine, famille_cible, enfant.pk)

        assurance.refresh_from_db()
        self.assertEqual(
            assurance.famille_id, famille_cible.pk,
            "L'assurance n'a pas été réattribuée à la famille cible.",
        )

    def test_reattribution_refuse_une_famille_non_rattachee(self):
        """Sécurité côté serveur : impossible de réattribuer vers une famille à laquelle
        l'individu n'est pas rattaché (contournement direct du formulaire)."""
        famille_origine = Famille.objects.create(nom="ASSUR ORIGINE2")
        famille_etrangere = Famille.objects.create(nom="ASSUR ETRANGERE")
        enfant = Individu.objects.create(nom="ASSURE2", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        # Pas de rattachement à famille_etrangere - l'enfant n'y appartient pas du tout.

        assureur = Assureur.objects.create(nom="MAIF")
        assurance = Assurance.objects.create(
            individu=enfant, famille=famille_origine, assureur=assureur,
            num_contrat="CTR456", date_debut=date(2026, 9, 1),
        )

        self._reattribuer(assurance, famille_origine, famille_etrangere, enfant.pk)

        assurance.refresh_from_db()
        self.assertEqual(
            assurance.famille_id, famille_origine.pk,
            "L'assurance a été réattribuée vers une famille à laquelle l'individu n'est "
            "pas rattaché - la vérification de sécurité côté serveur a été contournée.",
        )

    def test_reattribution_trace_lagent_dans_lhistorique(self):
        """Même exigence de traçabilité que pour les prestations : réattribuer une assurance
        déplace une donnée sensible d'une famille à une autre."""
        famille_origine = Famille.objects.create(nom="ASSUR TRACE ORIGINE")
        famille_cible = Famille.objects.create(nom="ASSUR TRACE CIBLE")
        enfant = Individu.objects.create(nom="ASSURTRACE", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        assureur = Assureur.objects.create(nom="MAIF")
        assurance = Assurance.objects.create(
            individu=enfant, famille=famille_origine, assureur=assureur,
            num_contrat="CTR789", date_debut=date(2026, 9, 1),
        )

        self._reattribuer(assurance, famille_origine, famille_cible, enfant.pk)

        log = Historique.objects.filter(individu_id=enfant.pk, titre__icontains="Réattribution").first()
        self.assertIsNotNone(log, "Aucune trace créée pour la réattribution de l'assurance.")
        self.assertIn("ASSUR TRACE ORIGINE", log.detail)
        self.assertIn("ASSUR TRACE CIBLE", log.detail)
        self.assertIsNotNone(log.utilisateur, "La trace ne dit pas quel agent a fait la réattribution.")


class TestReattributionInscription(TestCase):
    """Le bouton "Réattribuer à une autre famille" pour une inscription - même outil que pour
    les prestations et les assurances. Corrige le cas d'une inscription d'enfant partagé
    restée ambiguë après une séparation (aucun titulaire clair)."""

    @staticmethod
    def _creer_inscription(famille, individu):
        structure = Structure.objects.create(nom="Structure Test")
        activite = Activite.objects.create(nom="Cantine", abrege="CANT", structure=structure)
        groupe = Groupe.objects.create(activite=activite, nom="Groupe A", ordre=1)
        categorie_tarif = CategorieTarif.objects.create(activite=activite, nom="Standard")
        return Inscription.objects.create(
            individu=individu, famille=famille, activite=activite, groupe=groupe,
            categorie_tarif=categorie_tarif, date_debut=date(2026, 9, 1),
        )

    def _reattribuer(self, inscription, famille_origine, famille_cible, idindividu):
        request = RequestFactory().post("/", {"idfamille_cible": famille_cible.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = ReattribuerInscription()
        vue.request = request
        vue.kwargs = {"idfamille": famille_origine.pk, "idindividu": idindividu, "pk": inscription.pk}
        vue.post(request)

    def test_reattribution_deplace_linscription_vers_la_famille_cible(self):
        famille_origine = Famille.objects.create(nom="INSCR ORIGINE")
        famille_cible = Famille.objects.create(nom="INSCR CIBLE")
        enfant = Individu.objects.create(nom="INSCRIT", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        inscription = self._creer_inscription(famille_origine, enfant)

        self._reattribuer(inscription, famille_origine, famille_cible, enfant.pk)

        inscription.refresh_from_db()
        self.assertEqual(inscription.famille_id, famille_cible.pk)

    def test_reattribution_refuse_une_famille_non_rattachee(self):
        famille_origine = Famille.objects.create(nom="INSCR ORIGINE2")
        famille_etrangere = Famille.objects.create(nom="INSCR ETRANGERE")
        enfant = Individu.objects.create(nom="INSCRIT2", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)

        inscription = self._creer_inscription(famille_origine, enfant)

        self._reattribuer(inscription, famille_origine, famille_etrangere, enfant.pk)

        inscription.refresh_from_db()
        self.assertEqual(
            inscription.famille_id, famille_origine.pk,
            "L'inscription a été réattribuée vers une famille à laquelle l'individu n'est "
            "pas rattaché - la vérification de sécurité côté serveur a été contournée.",
        )

    def test_reattribution_trace_lagent_dans_lhistorique(self):
        famille_origine = Famille.objects.create(nom="INSCR TRACE ORIGINE")
        famille_cible = Famille.objects.create(nom="INSCR TRACE CIBLE")
        enfant = Individu.objects.create(nom="INSCRITTRACE", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        inscription = self._creer_inscription(famille_origine, enfant)

        self._reattribuer(inscription, famille_origine, famille_cible, enfant.pk)

        log = Historique.objects.filter(individu_id=enfant.pk, titre__icontains="Réattribution").first()
        self.assertIsNotNone(log, "Aucune trace créée pour la réattribution de l'inscription.")
        self.assertIn("INSCR TRACE ORIGINE", log.detail)
        self.assertIn("INSCR TRACE CIBLE", log.detail)
        self.assertIsNotNone(log.utilisateur)


class _FakeForm:
    """Simule un formulaire déjà validé : check_inscriptions_existantes ne lit que
    form.cleaned_data, pas besoin d'un vrai Formulaire Django pour ces tests."""
    def __init__(self, cleaned_data):
        self.cleaned_data = cleaned_data


class TestControleInscriptionCroiseeFamilles(TestCase):
    """check_inscriptions_existantes doit détecter un enfant déjà inscrit à la même activité
    sur une période qui se chevauche, que ce soit dans la même famille (déjà existant) ou une
    AUTRE famille (nouveau - sans ça, rien n'empêchait un enfant partagé d'être inscrit deux
    fois à la même activité, une fois par famille, jusqu'à ce qu'une fusion réunisse les deux
    prestations en double, impossibles à nettoyer une fois des consommations accrochées)."""

    def setUp(self):
        structure = Structure.objects.create(nom="Structure Test")
        self.activite = Activite.objects.create(nom="Cantine", abrege="CANT", structure=structure)
        self.groupe = Groupe.objects.create(activite=self.activite, nom="Groupe A", ordre=1)
        self.categorie_tarif = CategorieTarif.objects.create(activite=self.activite, nom="Standard")

    def _verifier(self, individu, famille, date_debut, date_fin=None, activite=None):
        request = RequestFactory().post("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)

        vue = Ajouter()
        vue.request = request
        form = _FakeForm({
            "activite": activite or self.activite, "individu": individu, "famille": famille,
            "date_debut": date_debut, "date_fin": date_fin,
        })
        return vue.check_inscriptions_existantes(form=form, instance=None)

    # ------------------------------------------------------------- même famille (non-régression)

    def test_bloque_meme_famille_periodes_qui_se_chevauchent(self):
        famille = Famille.objects.create(nom="CTRL1")
        enfant = Individu.objects.create(nom="CTRL1", prenom="Enfant", civilite=4)
        Inscription.objects.create(individu=enfant, famille=famille, activite=self.activite, groupe=self.groupe, categorie_tarif=self.categorie_tarif, date_debut=date(2026, 9, 1))

        self.assertFalse(self._verifier(enfant, famille, date(2026, 9, 15)))

    def test_autorise_meme_famille_periodes_disjointes(self):
        famille = Famille.objects.create(nom="CTRL2")
        enfant = Individu.objects.create(nom="CTRL2", prenom="Enfant", civilite=4)
        Inscription.objects.create(individu=enfant, famille=famille, activite=self.activite, groupe=self.groupe, categorie_tarif=self.categorie_tarif, date_debut=date(2023, 9, 1), date_fin=date(2024, 8, 31))

        self.assertTrue(self._verifier(enfant, famille, date(2026, 9, 1)))

    # ------------------------------------------------------------- autre famille (nouveau)

    def test_bloque_autre_famille_periodes_qui_se_chevauchent(self):
        famille_a = Famille.objects.create(nom="CTRL3A")
        famille_b = Famille.objects.create(nom="CTRL3B")
        enfant = Individu.objects.create(nom="CTRL3", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_a, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_b, categorie=2, titulaire=False)
        Inscription.objects.create(individu=enfant, famille=famille_a, activite=self.activite, groupe=self.groupe, categorie_tarif=self.categorie_tarif, date_debut=date(2026, 9, 1))

        self.assertFalse(
            self._verifier(enfant, famille_b, date(2026, 9, 15)),
            "Le doublon inter-familles n'a pas été détecté - c'est exactement le cas qui "
            "génère des prestations en double, impossibles à nettoyer après une fusion.",
        )

    def test_autorise_autre_famille_periodes_disjointes(self):
        famille_a = Famille.objects.create(nom="CTRL4A")
        famille_b = Famille.objects.create(nom="CTRL4B")
        enfant = Individu.objects.create(nom="CTRL4", prenom="Enfant", civilite=4)
        Inscription.objects.create(individu=enfant, famille=famille_a, activite=self.activite, groupe=self.groupe, categorie_tarif=self.categorie_tarif, date_debut=date(2023, 9, 1), date_fin=date(2024, 8, 31))

        self.assertTrue(
            self._verifier(enfant, famille_b, date(2026, 9, 1)),
            "Une vieille inscription terminée, dans une autre famille, bloque à tort une "
            "nouvelle inscription qui n'a pourtant aucun rapport (périodes disjointes).",
        )

    def test_autorise_autre_famille_si_inscriptions_multiples_active(self):
        structure = Structure.objects.create(nom="Structure Multi")
        activite_multi = Activite.objects.create(nom="Atelier", abrege="ATEL", structure=structure, inscriptions_multiples=True)
        groupe = Groupe.objects.create(activite=activite_multi, nom="Groupe", ordre=1)
        categorie_tarif = CategorieTarif.objects.create(activite=activite_multi, nom="Standard")
        famille_a = Famille.objects.create(nom="CTRL5A")
        famille_b = Famille.objects.create(nom="CTRL5B")
        enfant = Individu.objects.create(nom="CTRL5", prenom="Enfant", civilite=4)
        Inscription.objects.create(individu=enfant, famille=famille_a, activite=activite_multi, groupe=groupe, categorie_tarif=categorie_tarif, date_debut=date(2026, 9, 1))

        self.assertTrue(
            self._verifier(enfant, famille_b, date(2026, 9, 15), activite=activite_multi),
            "inscriptions_multiples=True doit toujours autoriser, même entre 2 familles.",
        )


@override_settings(ENT_URL="https://ent-test.example.com")
class TestGetUserOuIntrouvable(TestCase):
    """Vérifie directement au niveau HTTP (pas juste via un mock de haut niveau) que
    get_user_ou_introuvable distingue bien une vraie panne d'une confirmation ENT (404)
    que la personne n'existe plus - c'est le cœur du fix : avant, les deux cas étaient
    confondus (None dans les deux cas), ce qui faisait dire à tort "vérifiez la connexion"
    à un agent qui synchronise un élève ayant simplement quitté l'établissement."""

    def setUp(self):
        # Ce test vérifie au niveau HTTP réel, avec un vrai Organisateur en base - le patch
        # global du module (ENT actif simulé) doit s'effacer pour laisser passer celui-ci.
        _patch_ent_actif.stop()
        self.addCleanup(_patch_ent_actif.start)
        cache.delete("organisateur")
        Organisateur.objects.filter(pk=1).delete()
        Organisateur.objects.create(pk=1, ent_active=True)

    @staticmethod
    def _reponse(status_code, corps=None):
        resp = Mock()
        resp.status_code = status_code
        if status_code >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        else:
            resp.raise_for_status.return_value = None
        resp.json.return_value = corps or {}
        return resp

    def test_404_confirme_est_signale_comme_introuvable(self):
        with patch("core.utils.utils_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("core.utils.utils_ent.requests.get", return_value=self._reponse(404)):
            data, introuvable = get_user_ou_introuvable("ENT-PARTI")

        self.assertIsNone(data)
        self.assertTrue(introuvable)

    def test_vraie_panne_nest_pas_signalee_comme_introuvable(self):
        with patch("core.utils.utils_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("core.utils.utils_ent.requests.get", side_effect=requests.ConnectionError("panne réseau")):
            data, introuvable = get_user_ou_introuvable("ENT-X")

        self.assertIsNone(data)
        self.assertFalse(introuvable)

    def test_succes_normal_fonctionne_toujours(self):
        with patch("core.utils.utils_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("core.utils.utils_ent.requests.get", return_value=self._reponse(200, {"id": "ENT-X", "firstName": "Test"})):
            data, introuvable = get_user_ou_introuvable("ENT-X")

        self.assertEqual(data, {"id": "ENT-X", "firstName": "Test"})
        self.assertFalse(introuvable)


class TestSynchroniserIndividuIntrouvable(TestCase):
    """Cas ajoutés sur SynchroniserIndividu : message distinct quand la personne n'existe
    plus dans l'ENT, plutôt que le message générique "vérifiez la connexion"."""

    def setUp(self):
        self.famille = Famille.objects.create(nom="SYNCINTROUV")
        self.individu = Individu.objects.create(nom="SYNCINTROUV", prenom="Enfant", civilite=4, ent_id="ENT-SYNC-DISPARU")
        Rattachement.objects.create(individu=self.individu, famille=self.famille, categorie=2, titulaire=False)

    def _vue(self, request):
        vue = SynchroniserIndividu()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.individu.pk}
        vue.request = request
        return vue

    def test_affichage_message_distinct_si_personne_introuvable(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=(None, True)):
            context = self._vue(request).get_context_data()

        self.assertIn("n'existe plus dans l'ENT", context["erreur"])
        self.assertNotIn("Vérifiez la connexion", context["erreur"])

    def test_affichage_message_panne_reste_generique(self):
        """Non-régression : une vraie panne garde le message existant."""
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=(None, False)):
            context = self._vue(request).get_context_data()

        self.assertIn("Vérifiez la connexion", context["erreur"])

    def test_post_refuse_avec_message_distinct_si_personne_introuvable(self):
        request = RequestFactory().post("/", {"champs": ["nom"]})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=(None, True)):
            self._vue(request).post(request, idfamille=self.famille.pk, idindividu=self.individu.pk)

        self.individu.refresh_from_db()
        self.assertEqual(self.individu.nom, "SYNCINTROUV", "Rien ne devrait être modifié si la personne est introuvable côté ENT.")


class TestSynchroniserIndividuCasBase(TestCase):
    """Cas de base de l'écran de synchro individuelle : pas de lien ENT, aucun champ
    coché, valeur ENT vide écrite comme None plutôt que chaîne vide, comparaison qui ne
    modifie jamais rien toute seule (GET)."""

    def setUp(self):
        self.famille = Famille.objects.create(nom="SYNCBASE")

    def _vue(self, request, individu):
        vue = SynchroniserIndividu()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": individu.pk}
        vue.request = request
        return vue

    def test_individu_sans_ent_id(self):
        individu = Individu.objects.create(nom="SANSENTID", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=individu, famille=self.famille, categorie=2, titulaire=False)

        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        context = self._vue(request, individu).get_context_data()

        self.assertEqual(context["erreur"], "Cet individu n'a pas été importé depuis l'ENT.")

    def test_aucun_champ_coche_rien_nest_modifie(self):
        individu = Individu.objects.create(nom="AUCUNCHAMP", prenom="Enfant", civilite=4, ent_id="ENT-AUCUNCHAMP")
        Rattachement.objects.create(individu=individu, famille=self.famille, categorie=2, titulaire=False)

        request = RequestFactory().post("/", {})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=({"lastName": "NOUVEAU"}, False)):
            self._vue(request, individu).post(request, idfamille=self.famille.pk, idindividu=individu.pk)

        individu.refresh_from_db()
        self.assertEqual(individu.nom, "AUCUNCHAMP")
        msgs = [str(m) for m in get_messages(request)]
        self.assertTrue(any("Aucun champ sélectionné" in m for m in msgs))

    def test_valeur_ent_vide_ecrit_none(self):
        individu = Individu.objects.create(nom="VIDETEST", prenom="Enfant", civilite=4, ent_id="ENT-VIDETEST", mail="ancien@test.fr")
        Rattachement.objects.create(individu=individu, famille=self.famille, categorie=2, titulaire=False)

        request = RequestFactory().post("/", {"champs": ["mail"]})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=({"email": ""}, False)):
            self._vue(request, individu).post(request, idfamille=self.famille.pk, idindividu=individu.pk)

        individu.refresh_from_db()
        self.assertIsNone(individu.mail)

    def test_comparaison_detecte_les_ecarts_sans_rien_modifier(self):
        individu = Individu.objects.create(nom="COMPAR", prenom="Enfant", civilite=4, ent_id="ENT-COMPAR", mail="ancien@test.fr")
        Rattachement.objects.create(individu=individu, famille=self.famille, categorie=2, titulaire=False)

        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=({"lastName": "COMPAR", "email": "nouveau@test.fr"}, False)):
            context = self._vue(request, individu).get_context_data()

        ligne_mail = next(l for l in context["lignes"] if l["code"] == "mail")
        self.assertTrue(ligne_mail["different"])
        ligne_nom = next(l for l in context["lignes"] if l["code"] == "nom")
        self.assertFalse(ligne_nom["different"])

        individu.refresh_from_db()
        self.assertEqual(individu.mail, "ancien@test.fr", "Le simple affichage (GET) ne doit jamais modifier la fiche.")

    def test_synchroniser_le_nom_dun_titulaire_recalcule_le_nom_de_famille(self):
        """Famille.nom n'est jamais recalculé automatiquement (pas de signal Django) - une
        synchro qui change le nom d'un titulaire doit donc rappeler Maj_infos() elle-même,
        sinon la fiche famille garde l'ancien nom indéfiniment."""
        parent = Individu.objects.create(nom="AVANTSYNC", prenom="Papa", civilite=1, ent_id="ENT-TITULAIRE-SYNC")
        Rattachement.objects.create(individu=parent, famille=self.famille, categorie=1, titulaire=True)
        self.famille.Maj_infos()
        self.assertIn("AVANTSYNC", self.famille.nom)

        request = RequestFactory().post("/", {"champs": ["nom"]})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_individu.views.individu_ent.get_user_ou_introuvable", return_value=({"lastName": "APRESSYNC"}, False)):
            self._vue(request, parent).post(request, idfamille=self.famille.pk, idindividu=parent.pk)

        self.famille.refresh_from_db()
        self.assertIn("APRESSYNC", self.famille.nom)
        self.assertNotIn("AVANTSYNC", self.famille.nom)


class TestGetLignesComparaisonEcoleClasse(TestCase):
    """La ligne École/Classe ne doit jamais être proposée pour un parent (piège : l'ENT
    renvoie aussi un champ "structures" pour les parents - un rattachement administratif,
    pas une vraie scolarité), et doit être marquée non synchronisable si l'école n'est pas
    encore connue de Noethys."""

    def test_parent_avec_structure_ne_propose_pas_ecole_classe(self):
        individu = Individu.objects.create(nom="PARENTSTRUCT", prenom="Papa", civilite=1)
        data_ent = {
            "type": "Relative", "lastName": "PARENTSTRUCT", "firstName": "Papa",
            "structures": [{"name": "École Test Piege", "uai": None, "id": "ENT-ECOLE-PIEGE"}],
        }

        lignes = Get_lignes_comparaison(individu, data_ent)

        self.assertFalse(
            any(l["code"] == "ecole_classe" for l in lignes),
            "La ligne École/Classe ne doit jamais apparaître pour un parent.",
        )

    def test_eleve_ecole_non_reconnue_nest_pas_cochable(self):
        individu = Individu.objects.create(nom="ELEVEECOLEKO", prenom="Enfant", civilite=4)
        data_ent = {
            "type": "Student", "lastName": "ELEVEECOLEKO", "firstName": "Enfant",
            "structures": [{"name": "École Jamais Connue Synchro", "uai": None, "id": "ENT-ECOLE-JAMAIS"}],
        }

        lignes = Get_lignes_comparaison(individu, data_ent)

        ligne = next(l for l in lignes if l["code"] == "ecole_classe")
        self.assertTrue(ligne["ecole_non_reconnue"])

    def test_eleve_ecole_reconnue_est_cochable(self):
        Ecole.objects.create(nom="École Synchro Connue", ent_id="ENT-ECOLE-SYNCHRO-OK")
        individu = Individu.objects.create(nom="ELEVEECOLEOK", prenom="Enfant", civilite=4)
        data_ent = {
            "type": "Student", "lastName": "ELEVEECOLEOK", "firstName": "Enfant",
            "structures": [{"name": "École Synchro Connue", "uai": None, "id": "ENT-ECOLE-SYNCHRO-OK"}],
        }

        lignes = Get_lignes_comparaison(individu, data_ent)

        ligne = next(l for l in lignes if l["code"] == "ecole_classe")
        self.assertFalse(ligne["ecole_non_reconnue"])


class TestAppliquerSyncEcoleClasse(TestCase):
    """Appliquer_sync_ecole_classe : création de scolarité si absente, mise à jour si
    déjà existante (pas de doublon), choix de la scolarité "actuelle", et dates par défaut
    si l'ENT n'en fournit pas (observé systématiquement en pratique)."""

    def test_cree_une_scolarite_si_absente(self):
        ecole = Ecole.objects.create(nom="École C8", ent_id="ENT-ECOLE-C8")
        individu = Individu.objects.create(nom="C8", prenom="Enfant", civilite=4)
        data_ent = {"type": "Student", "structures": [{"name": "École C8", "uai": None, "id": "ENT-ECOLE-C8"}], "allClasses": [{"name": "CE1"}]}

        resultat = Appliquer_sync_ecole_classe(individu, data_ent)

        self.assertTrue(resultat)
        scolarite = Scolarite.objects.get(individu=individu)
        self.assertEqual(scolarite.ecole, ecole)
        self.assertEqual(scolarite.classe.nom, "CE1")

    def test_met_a_jour_la_scolarite_existante_plutot_que_den_creer_une(self):
        ecole_avant = Ecole.objects.create(nom="École C9 Avant")
        ecole_apres = Ecole.objects.create(nom="École C9 Apres", ent_id="ENT-ECOLE-C9")
        individu = Individu.objects.create(nom="C9", prenom="Enfant", civilite=4)
        scolarite = Scolarite.objects.create(individu=individu, ecole=ecole_avant, date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31))
        data_ent = {"type": "Student", "structures": [{"name": "École C9 Apres", "uai": None, "id": "ENT-ECOLE-C9"}], "allClasses": [{"name": "CM2"}]}

        Appliquer_sync_ecole_classe(individu, data_ent)

        self.assertEqual(Scolarite.objects.filter(individu=individu).count(), 1, "Doit mettre à jour la ligne existante, pas en créer une deuxième.")
        scolarite.refresh_from_db()
        self.assertEqual(scolarite.ecole, ecole_apres)
        self.assertEqual(scolarite.classe.nom, "CM2")

    def test_scolarite_actuelle_est_celle_qui_couvre_aujourdhui(self):
        ecole = Ecole.objects.create(nom="École C10")
        individu = Individu.objects.create(nom="C10", prenom="Enfant", civilite=4)
        Scolarite.objects.create(individu=individu, ecole=ecole, date_debut=date(2020, 9, 1), date_fin=date(2021, 8, 31))
        actuelle = Scolarite.objects.create(individu=individu, ecole=ecole, date_debut=date(2025, 9, 1), date_fin=date(2099, 8, 31))

        resultat = Get_scolarite_actuelle(individu)

        self.assertEqual(resultat.pk, actuelle.pk)

    def test_scolarite_actuelle_est_la_plus_recente_si_aucune_ne_couvre_aujourdhui(self):
        ecole = Ecole.objects.create(nom="École C10b")
        individu = Individu.objects.create(nom="C10b", prenom="Enfant", civilite=4)
        Scolarite.objects.create(individu=individu, ecole=ecole, date_debut=date(2018, 9, 1), date_fin=date(2019, 8, 31))
        plus_recente = Scolarite.objects.create(individu=individu, ecole=ecole, date_debut=date(2020, 9, 1), date_fin=date(2021, 8, 31))

        resultat = Get_scolarite_actuelle(individu)

        self.assertEqual(resultat.pk, plus_recente.pk)

    def test_dates_par_defaut_si_absentes_cote_ent(self):
        ecole = Ecole.objects.create(nom="École C12", ent_id="ENT-ECOLE-C12")
        individu = Individu.objects.create(nom="C12", prenom="Enfant", civilite=4)
        data_ent = {"type": "Student", "structures": [{"name": "École C12", "uai": None, "id": "ENT-ECOLE-C12"}], "allClasses": [{"name": "CP"}]}
        # Pas de startDateClasses/endDateClasses fourni - cas observé systématiquement côté ENT

        Appliquer_sync_ecole_classe(individu, data_ent)

        annee_debut, annee_fin = _get_annee_scolaire_par_defaut()
        classe = Scolarite.objects.get(individu=individu).classe
        self.assertEqual(classe.date_debut, annee_debut)
        self.assertEqual(classe.date_fin, annee_fin)

    def test_ne_cree_rien_si_ecole_inconnue(self):
        """D3.6 : contrairement au cas où l'école est connue, aucune scolarité ne doit
        être créée ni modifiée si l'école ENT n'est pas encore reconnue de Noethys."""
        individu = Individu.objects.create(nom="D36", prenom="Enfant", civilite=4)
        data_ent = {"type": "Student", "structures": [{"name": "École Jamais Connue D36", "uai": None, "id": "ENT-ECOLE-D36"}], "allClasses": [{"name": "CE1"}]}

        resultat = Appliquer_sync_ecole_classe(individu, data_ent)

        self.assertFalse(resultat)
        self.assertFalse(Scolarite.objects.filter(individu=individu).exists())


class TestEcransEntIndividuelsBloquesSiEntDesactive(TestCase):
    """La synchro individuelle et l'outil de liaison/déliaison doivent rester inaccessibles
    même par une URL tapée à la main quand l'ENT est désactivé dans Paramétrage."""

    def setUp(self):
        self.famille = Famille.objects.create(nom="ENTINACTIF")
        self.individu = Individu.objects.create(nom="ENTINACTIF", prenom="Enfant", civilite=4, ent_id="ENT-INACTIF")
        Rattachement.objects.create(individu=self.individu, famille=self.famille, categorie=2, titulaire=False)

    def _requete(self, methode="get", data=None):
        request = getattr(RequestFactory(), methode)("/", data or {})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        return request

    def test_synchroniser_individu_get_signale_ent_inactif(self):
        vue = SynchroniserIndividu()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.individu.pk}
        vue.request = self._requete()

        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            context = vue.get_context_data()

        self.assertEqual(context["erreur"], "L'intégration ENT est désactivée.")

    def test_synchroniser_individu_post_bloque_si_ent_inactif(self):
        vue = SynchroniserIndividu()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.individu.pk}
        request = self._requete("post")

        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            response = vue.post(request, idfamille=self.famille.pk, idindividu=self.individu.pk)

        self.assertEqual(response.status_code, 302)

    def test_lier_compte_ent_get_bloque_si_ent_inactif(self):
        vue = LierCompteEnt()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.individu.pk}
        request = self._requete()

        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            response = vue.get(request)

        self.assertEqual(response.status_code, 302)

    def test_lier_compte_ent_post_bloque_si_ent_inactif(self):
        vue = LierCompteEnt()
        vue.kwargs = {"idfamille": self.famille.pk, "idindividu": self.individu.pk}
        request = self._requete("post")

        with patch("core.utils.utils_ent._get_organisateur", return_value=SimpleNamespace(ent_active=False)):
            response = vue.post(request)

        self.assertEqual(response.status_code, 302)
