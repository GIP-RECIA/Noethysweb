# -*- coding: utf-8 -*-
"""
Tests de la logique de corroboration ENT - pré-liaison en masse (PreLiaisonEnt).

IMPORTANT : ces tests vérifient le comportement ATTENDU (règles métier validées),
pas forcément le comportement actuel du code. Un test rouge signale un écart du
code par rapport à la règle, pas une erreur du test.

Aucun appel réseau réel : search_by_name / get_headers sont mockés, et le
ThreadPoolExecutor est remplacé par une exécution en série (les threads ne
verraient pas les données de la transaction de test).
"""

from datetime import date
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import Famille, Individu, Rattachement
from fiche_famille.views.famille_ent import PreLiaisonEnt


class _SerialExecutor:
    """Remplace ThreadPoolExecutor : exécute map() en série, dans le même thread
    (et donc dans la même transaction de test)."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, fn, iterable):
        return [fn(x) for x in iterable]


def _resultat_eleve(ent_id, nom, prenom, birth=None, parents=None):
    return {
        "id": ent_id,
        "type": "Student",
        "firstName": prenom,
        "lastName": nom,
        "birthDate": birth,
        "parents": list(parents or []),
    }


class TestCorroborationPreLiaison(TestCase):

    def _lancer_recherche(self, reponses_par_prenom):
        """Lance la pré-liaison complète avec des réponses ENT simulées.
        reponses_par_prenom : {prenom: [resultats ENT]} (dicts recréés à chaque appel
        pour éviter qu'un résultat mutés par un enfant ne pollue le suivant)."""

        def fake_search(last_name=None, first_name=None):
            fabrique = reponses_par_prenom.get(first_name)
            return fabrique() if fabrique else []

        with patch("fiche_individu.views.individu_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_individu.views.individu_ent.search_by_name", side_effect=fake_search), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            return PreLiaisonEnt()._rechercher_toutes_correspondances()

    @staticmethod
    def _cles_proposees(groupes):
        return [ligne["cle"] for groupe in groupes for ligne in groupe["lignes"]]

    # ------------------------------------------------------------------ règle 1

    def test_regle1_enfant_dont_le_compte_candidat_est_deja_pris_nest_pas_propose(self):
        """Règle 1 : un enfant dont le compte ENT candidat est déjà utilisé par un
        autre individu Noethys ne doit jamais être proposé en pré-liaison."""
        # Un autre individu, sans rapport, détient déjà le compte candidat
        Individu.objects.create(nom="AUTRE", prenom="Individu", civilite=4, ent_id="ENT-J")

        famille = Famille.objects.create(nom="PRELTEST")
        parent = Individu.objects.create(nom="PRELTEST", prenom="Gabriel", civilite=1)
        enfant = Individu.objects.create(nom="PRELTEST", prenom="Julia", civilite=4)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({
            "Julia": lambda: [_resultat_eleve("ENT-J", "PRELTEST", "Julia", parents=[
                {"firstName": "Gabriel", "lastName": "PRELTEST", "id": "ENT-G"},
            ])],
        })

        cles = self._cles_proposees(groupes)
        self.assertNotIn(
            f"ENT-J|{enfant.pk}", cles,
            "L'enfant est proposé en pré-liaison alors que son compte ENT candidat "
            "est déjà utilisé par un autre individu Noethys (la confirmation "
            "échouerait silencieusement).",
        )

    def test_regle5d_preliaison_ne_propose_pas_les_cas_corrobores_par_la_date_seule(self):
        """La date seule suffit sur l'écran individuel (avec avertissement), mais pas pour
        une proposition automatique cochée d'avance en pré-liaison : ces cas basculent en
        "à vérifier à la main" avec une raison explicite."""
        famille = Famille.objects.create(nom="DATESEULE")
        # Enfant SEUL dans sa famille : aucun parent ne pourra corroborer
        enfant = Individu.objects.create(nom="DATESEULE", prenom="Lucas", civilite=4,
                                        date_naiss=date(2005, 4, 10))
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({
            "Lucas": lambda: [_resultat_eleve("ENT-L", "DATESEULE", "Lucas", birth="2005-04-10", parents=[
                {"firstName": "Alice", "lastName": "DATESEULE", "id": "ENT-A"},
            ])],
        })

        self.assertNotIn(
            f"ENT-L|{enfant.pk}", self._cles_proposees(groupes),
            "Un cas corroboré par la seule date de naissance est proposé automatiquement, "
            "coché d'avance, alors qu'aucun parent ne corrobore.",
        )
        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons, "Le cas a disparu au lieu d'être listé à vérifier.")
        self.assertIn("date de naissance", raisons[0])

    # ------------------------------------------------------------------ règle 6

    def test_regle6_collision_deux_familles_aucune_retenue(self):
        """Règle 6 : deux familles Noethys différentes qui correspondent au même
        compte ENT => aucune des deux n'est retenue."""
        for suffixe in ("A", "C"):
            famille = Famille.objects.create(nom=f"COLLTEST {suffixe}")
            parent = Individu.objects.create(nom="COLLTEST", prenom="Gabriel", civilite=1)
            enfant = Individu.objects.create(nom="COLLTEST", prenom="Julia", civilite=4)
            Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
            Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({
            "Julia": lambda: [_resultat_eleve("ENT-J", "COLLTEST", "Julia", parents=[
                {"firstName": "Gabriel", "lastName": "COLLTEST", "id": "ENT-G"},
            ])],
        })

        self.assertEqual(
            groupes, [],
            "Au moins une des deux familles en collision a été retenue - le même "
            "compte ENT ne peut pas être proposé à deux personnes différentes.",
        )
        # Les deux enfants doivent être visibles dans les non-résolus (pas perdus)
        enfants_non_resolus = [p["individu_id"] for g in non_resolus for p in g["personnes"] if p["role"] == "Enfant"]
        self.assertEqual(len(enfants_non_resolus), 2)

    def test_regle6b_collision_de_parents_est_signalee_sans_bloquer_les_enfants(self):
        """Règle 6 (parents) : deux fiches Noethys différentes qui correspondent au même
        compte ENT parent (fiche en double) doivent être signalées à l'agent - et les
        enfants, eux, restent proposés puisque leurs propres comptes ne sont pas ambigus."""
        # Deux enfants DISTINCTS (Lea et Tom), dans deux familles Noethys séparées, mais
        # le même vrai père saisi deux fois (une fiche par famille).
        familles = {}
        for prenom_enfant, suffixe in (("Lea", "A"), ("Tom", "B")):
            famille = Famille.objects.create(nom=f"MARTIN {suffixe}")
            parent = Individu.objects.create(nom="MARTIN", prenom="Marc", civilite=1)
            enfant = Individu.objects.create(nom="MARTIN", prenom=prenom_enfant, civilite=4)
            Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
            Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
            familles[prenom_enfant] = {"famille": famille, "parent": parent, "enfant": enfant}

        # Côté ENT : Lea et Tom sont frère et soeur, même père (ENT-MARC)
        parent_ent = [{"firstName": "Marc", "lastName": "MARTIN", "id": "ENT-MARC"}]
        groupes, non_resolus = self._lancer_recherche({
            "Lea": lambda: [_resultat_eleve("ENT-LEA", "MARTIN", "Lea", parents=list(parent_ent))],
            "Tom": lambda: [_resultat_eleve("ENT-TOM", "MARTIN", "Tom", parents=list(parent_ent))],
        })

        # Les deux fiches parent en double doivent être signalées à l'agent
        parents_signales = [p for g in non_resolus for p in g["personnes"] if p["role"] == "Parent"]
        self.assertEqual(
            len(parents_signales), 2,
            "Les fiches parent en double ont été retirées des propositions sans être "
            "signalées - l'agent ne peut pas savoir qu'il a un doublon à corriger.",
        )

        # Les enfants, eux, ne sont pas ambigus : ils restent proposés
        cles = self._cles_proposees(groupes)
        self.assertIn(f"ENT-LEA|{familles['Lea']['enfant'].pk}", cles)
        self.assertIn(f"ENT-TOM|{familles['Tom']['enfant'].pk}", cles)
        # ... et le parent en double n'est évidemment plus proposé
        self.assertFalse([c for c in cles if c.startswith("ENT-MARC|")])

    # ------------------------------------------------------------------ règle 8

    def test_regle8c_confirm_pre_liaison_n_ecrase_pas_un_ent_id_existant(self):
        """Règle 8 : la confirmation de pré-liaison ne doit jamais écraser un ent_id
        déjà existant, même si la clé est envoyée directement."""
        famille = Famille.objects.create(nom="CONFTEST")
        enfant = Individu.objects.create(nom="CONFTEST", prenom="Julia", civilite=4, ent_id="ANCIEN-COMPTE")
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        request = RequestFactory().post("/", {
            "action": "confirmer",
            "liaisons_confirmees": [f"NOUVEAU-COMPTE|{enfant.pk}"],
        })
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)

        vue = PreLiaisonEnt()
        vue.request = request
        vue.kwargs = {}
        vue.post(request)

        enfant.refresh_from_db()
        self.assertEqual(
            enfant.ent_id, "ANCIEN-COMPTE",
            "L'ent_id existant a été écrasé par la confirmation de pré-liaison.",
        )
