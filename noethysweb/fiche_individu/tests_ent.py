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
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.utils import timezone

from core.models import Classe, Ecole, Famille, Historique, Individu, Rattachement, Scolarite, Utilisateur
from fiche_individu.views.individu_ent import LierCompteEnt


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
