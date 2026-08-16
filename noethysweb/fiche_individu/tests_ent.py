# -*- coding: utf-8 -*-
"""
Tests de la logique de corroboration ENT - liaison individuelle (LierCompteEnt).

IMPORTANT : ces tests vérifient le comportement ATTENDU (règles métier validées),
pas forcément le comportement actuel du code. Un test rouge signale un écart du
code par rapport à la règle, pas une erreur du test.

Aucun appel réseau réel : search_by_name / get_headers sont mockés.
"""

from datetime import date
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import Famille, Individu, Rattachement
from fiche_individu.views.individu_ent import LierCompteEnt


def _resultat_eleve(ent_id, nom, prenom, birth=None, parents=None):
    """Fabrique un résultat ENT au format admin/list pour un élève."""
    return {
        "id": ent_id,
        "type": "Student",
        "firstName": prenom,
        "lastName": nom,
        "birthDate": birth,
        "parents": list(parents or []),
    }


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
        return request

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
        self.vue.post(request, idfamille=self.famille.pk, idindividu=self.enfant.pk)

        self.parent.refresh_from_db()
        self.assertEqual(
            self.parent.ent_id, "ANCIEN-COMPTE-PARENT",
            "L'ent_id existant du parent a été écrasé.",
        )
