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

import uuid
from datetime import date
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import Activite, CategorieTarif, Classe, Cotisation, Deduction, Ecole, Famille, Groupe, Historique, Individu, Inscription, Prestation, Rattachement, Scolarite, Structure, TypeCotisation, UniteCotisation, Utilisateur
from fiche_famille.views.famille_ent import FusionnerFamilles, ImporterFamilleEnt, PreLiaisonEnt, SeparerFamille, _importer_eleve_ent
from fiche_famille.views.famille_prestations import ReattribuerPrestation


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


def _resultat_eleve(ent_id, nom, prenom, birth=None, parents=None, ecole=None, classe=None, ecole_uai=None, ecole_ent_id=None):
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

    def test_ecole_seule_nest_pas_proposee_automatiquement_en_preliaison(self):
        """Même traitement que la date seule : l'école/classe seule peut corroborer, mais
        ne doit pas être proposée automatiquement en pré-liaison - elle bascule en "à
        vérifier à la main"."""
        famille = Famille.objects.create(nom="ECOLESEULE")
        enfant = Individu.objects.create(nom="ECOLESEULE", prenom="Lucas", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        ecole = Ecole.objects.create(nom="École Test", uai="UAI999", ent_id="ENT-ECOLE-1")
        classe = Classe.objects.create(ecole=ecole, nom="CE2 A", date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))
        Scolarite.objects.create(individu=enfant, ecole=ecole, classe=classe, date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))

        groupes, non_resolus = self._lancer_recherche({
            "Lucas": lambda: [_resultat_eleve(
                "ENT-L", "ECOLESEULE", "Lucas", ecole="École Test", ecole_uai="UAI999", ecole_ent_id="ENT-ECOLE-1", classe="CE2 A",
                parents=[{"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"}],
            )],
        })

        self.assertNotIn(
            f"ENT-L|{enfant.pk}", self._cles_proposees(groupes),
            "Un cas corroboré par la seule école/classe est proposé automatiquement, coché "
            "d'avance, alors qu'aucun parent ne corrobore.",
        )
        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons, "Le cas a disparu au lieu d'être listé à vérifier.")
        self.assertIn("école", raisons[0])

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

    def test_regle6c_collision_departagee_par_date_de_naissance(self):
        """Règle 6 (départage) : deux familles Noethys en collision sur le même compte ENT
        enfant, mais une seule a une date de naissance cohérente avec l'ENT => elle est
        retenue automatiquement, l'autre est écartée avec une raison explicite.

        Note : si la date de Noethys ETAIT connue et contredisait franchement l'ENT, le
        veto de la règle 3 (nom_corrobore + date_coherente=False) exclurait déjà cette
        famille avant même d'atteindre la détection de collision - ce n'est donc pas
        départagé par ce mécanisme mais par le veto existant. Le cas que ce mécanisme sert
        vraiment à trancher, c'est quand une des deux dates est simplement INCONNUE côté
        Noethys (pas de contradiction franche, juste rien à comparer)."""
        famille_a = Famille.objects.create(nom="COLLDATE A")
        parent_a = Individu.objects.create(nom="COLLDATE", prenom="Gabriel", civilite=1)
        enfant_a = Individu.objects.create(nom="COLLDATE", prenom="Julia", civilite=4, date_naiss=date(2010, 5, 1))
        Rattachement.objects.create(individu=parent_a, famille=famille_a, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant_a, famille=famille_a, categorie=2, titulaire=False)

        famille_c = Famille.objects.create(nom="COLLDATE C")
        parent_c = Individu.objects.create(nom="COLLDATE", prenom="Gabriel", civilite=1)
        enfant_c = Individu.objects.create(nom="COLLDATE", prenom="Julia", civilite=4)  # date de naissance inconnue
        Rattachement.objects.create(individu=parent_c, famille=famille_c, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant_c, famille=famille_c, categorie=2, titulaire=False)

        familles = {"A": {"famille": famille_a, "enfant": enfant_a}, "C": {"famille": famille_c, "enfant": enfant_c}}

        groupes, non_resolus = self._lancer_recherche({
            "Julia": lambda: [_resultat_eleve("ENT-J", "COLLDATE", "Julia", birth="2010-05-01", parents=[
                {"firstName": "Gabriel", "lastName": "COLLDATE", "id": "ENT-G"},
            ])],
        })

        cles = self._cles_proposees(groupes)
        self.assertIn(
            f"ENT-J|{familles['A']['enfant'].pk}", cles,
            "La famille dont la date de naissance correspond n'a pas été retenue - "
            "le départage par la date de naissance n'a pas fonctionné.",
        )
        self.assertNotIn(f"ENT-J|{familles['C']['enfant'].pk}", cles)

        raisons_c = [p["raison"] for g in non_resolus if g["famille_id"] == familles["C"]["famille"].pk for p in g["personnes"]]
        self.assertTrue(raisons_c, "La famille écartée par le départage doit être signalée en 'à vérifier'.")
        self.assertIn("départagé", raisons_c[0])

    def test_regle6d_collision_departagee_par_ecole_si_date_ne_suffit_pas(self):
        """Règle 6 (départage, repli) : si la date de naissance ne permet pas de trancher
        (aucune date connue des deux côtés), l'école/classe sert de critère de repli."""
        ecole = Ecole.objects.create(nom="École Test", uai="UAI999", ent_id="ENT-ECOLE-1")
        classe = Classe.objects.create(ecole=ecole, nom="CE2 A", date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))

        familles = {}
        for suffixe, avec_ecole in (("A", True), ("C", False)):
            famille = Famille.objects.create(nom=f"COLLECOLE {suffixe}")
            parent = Individu.objects.create(nom="COLLECOLE", prenom="Gabriel", civilite=1)
            enfant = Individu.objects.create(nom="COLLECOLE", prenom="Julia", civilite=4)
            Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
            Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
            if avec_ecole:
                Scolarite.objects.create(individu=enfant, ecole=ecole, classe=classe, date_debut=date(2020, 9, 1), date_fin=date(2030, 8, 31))
            familles[suffixe] = {"famille": famille, "enfant": enfant}

        groupes, non_resolus = self._lancer_recherche({
            "Julia": lambda: [_resultat_eleve(
                "ENT-J", "COLLECOLE", "Julia", ecole="École Test", ecole_uai="UAI999", ecole_ent_id="ENT-ECOLE-1", classe="CE2 A",
                parents=[{"firstName": "Gabriel", "lastName": "COLLECOLE", "id": "ENT-G"}],
            )],
        })

        cles = self._cles_proposees(groupes)
        self.assertIn(f"ENT-J|{familles['A']['enfant'].pk}", cles)
        self.assertNotIn(f"ENT-J|{familles['C']['enfant'].pk}", cles)

    def test_departage_retire_aussi_le_parent_devenu_sans_fondement(self):
        """Une ligne Parent n'est proposée que parce qu'un enfant précis a permis de la
        corroborer. Si cet enfant est écarté par un départage, la proposition sur le parent
        n'a plus aucune preuve - elle doit être retirée aussi, sinon on continue à proposer
        de lier un parent à un compte ENT dont on vient de décider qu'il n'est pas le bon."""
        famille_a = Famille.objects.create(nom="ORPHELIN A")
        marc = Individu.objects.create(nom="MOREAU", prenom="Marc", civilite=1)
        lea_a = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4, date_naiss=date(2012, 3, 4))
        Rattachement.objects.create(individu=marc, famille=famille_a, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=lea_a, famille=famille_a, categorie=2, titulaire=False)

        # Famille homonyme sans rapport réel avec la famille A - sa "Sophie MOREAU" est une
        # personne différente qui porte, par coïncidence, le même nom que la mère listée côté ENT.
        famille_c = Famille.objects.create(nom="ORPHELIN C")
        sophie = Individu.objects.create(nom="MOREAU", prenom="Sophie", civilite=3)
        lea_c = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4)  # date inconnue
        Rattachement.objects.create(individu=sophie, famille=famille_c, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=lea_c, famille=famille_c, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({
            "Lea": lambda: [_resultat_eleve("ENT-LEA", "MOREAU", "Lea", birth="2012-03-04", parents=[
                {"firstName": "Marc", "lastName": "MOREAU", "id": "ENT-MARC"},
                {"firstName": "Sophie", "lastName": "MOREAU", "id": "ENT-SOPHIE"},
            ])],
        })

        cles = self._cles_proposees(groupes)
        self.assertIn(f"ENT-LEA|{lea_a.pk}", cles, "La famille A (date correcte) doit gagner le départage.")
        self.assertIn(f"ENT-MARC|{marc.pk}", cles, "Le parent de la famille gagnante doit rester proposé.")
        self.assertNotIn(f"ENT-LEA|{lea_c.pk}", cles)
        self.assertNotIn(
            f"ENT-SOPHIE|{sophie.pk}", cles,
            "Le parent de la famille perdante reste proposé alors que son seul enfant "
            "justificatif (Lea C) a été écarté par le départage - la proposition n'a plus "
            "aucun fondement.",
        )

        raisons_sophie = [
            p["raison"] for g in non_resolus if g["famille_id"] == famille_c.pk
            for p in g["personnes"] if p["individu_id"] == sophie.pk
        ]
        self.assertTrue(raisons_sophie, "Sophie a disparu au lieu d'être listée à vérifier.")

    def test_departage_ne_retire_pas_un_parent_encore_justifie_par_un_frere(self):
        """Si un parent est corroboré via 2 enfants d'une même fratrie, et que l'un des deux
        est écarté par un départage (perdu contre une autre famille), le parent reste
        légitimement corroboré par l'autre enfant - il ne doit PAS être retiré. Le retirer
        priverait l'agent d'une proposition pourtant toujours valable."""
        famille_a = Famille.objects.create(nom="FRATRIE A")
        marc = Individu.objects.create(nom="MOREAU", prenom="Marc", civilite=1)
        lea_a = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4)  # date inconnue -> va perdre
        tom_a = Individu.objects.create(nom="MOREAU", prenom="Tom", civilite=4)
        Rattachement.objects.create(individu=marc, famille=famille_a, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=lea_a, famille=famille_a, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=tom_a, famille=famille_a, categorie=2, titulaire=False)

        # Famille homonyme sans rapport réel, dont la Lea a la bonne date de naissance -> elle
        # gagne le départage sur ENT-LEA, aux dépens de Lea de la famille A.
        famille_b = Famille.objects.create(nom="FRATRIE B")
        sophie_b = Individu.objects.create(nom="DIFFERENT", prenom="Sophie", civilite=3)
        lea_b = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4, date_naiss=date(2012, 3, 4))
        Rattachement.objects.create(individu=sophie_b, famille=famille_b, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=lea_b, famille=famille_b, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({
            "Lea": lambda: [_resultat_eleve("ENT-LEA", "MOREAU", "Lea", birth="2012-03-04", parents=[
                {"firstName": "Marc", "lastName": "MOREAU", "id": "ENT-MARC"},
                {"firstName": "Sophie", "lastName": "DIFFERENT", "id": "ENT-SOPHIE-B"},
            ])],
            "Tom": lambda: [_resultat_eleve("ENT-TOM", "MOREAU", "Tom", parents=[
                {"firstName": "Marc", "lastName": "MOREAU", "id": "ENT-MARC"},
            ])],
        })

        cles = self._cles_proposees(groupes)
        self.assertIn(f"ENT-LEA|{lea_b.pk}", cles, "La famille B (date correcte) doit gagner le départage.")
        self.assertNotIn(f"ENT-LEA|{lea_a.pk}", cles, "Lea de la famille A doit perdre le départage.")
        self.assertIn(f"ENT-TOM|{tom_a.pk}", cles, "Tom n'est concerné par aucune collision.")
        self.assertIn(
            f"ENT-MARC|{marc.pk}", cles,
            "Marc a été retiré alors que Tom (son autre enfant, non écarté) le justifie "
            "toujours - un parent ne doit être retiré que si TOUS ses enfants justificatifs "
            "ont été écartés.",
        )

    # ------------------------------------------------- panne ENT vs absence de résultat

    def test_panne_en_masse_ne_dit_pas_que_les_enfants_nexistent_pas(self):
        """En traitement de masse, une panne ENT touchait chaque enfant traité pendant
        l'incident avec la raison "n'existe peut-être pas dans l'ENT" - un diagnostic faux
        répété des centaines de fois, qui pousse l'agent à importer des doublons."""
        famille = Famille.objects.create(nom="PANNE")
        enfant = Individu.objects.create(nom="PANNE", prenom="Lucas", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        # search_by_name renvoie None = l'ENT n'a pas répondu (et non [] = aucun résultat)
        groupes, non_resolus = self._lancer_recherche({"Lucas": lambda: None})

        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons, "L'enfant a disparu au lieu d'être listé à vérifier.")
        self.assertIn("connexion", raisons[0].lower())
        self.assertNotIn(
            "n'y existe peut-être pas", raisons[0],
            "Une panne ENT est annoncée comme une absence de fiche - l'agent conclura à tort "
            "qu'il faut créer/importer cette personne.",
        )

    # ------------------------------------------ confirmation : jamais d'échec silencieux

    def _confirmer(self, cles, groupes_session):
        """Simule le clic 'Confirmer les liaisons sélectionnées' et renvoie les messages."""
        request = RequestFactory().post("/", {"action": "confirmer", "liaisons_confirmees": cles})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session[PreLiaisonEnt.SESSION_KEY] = {"groupes": groupes_session, "non_resolus": []}
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = PreLiaisonEnt()
        vue.request = request
        vue.kwargs = {}
        vue.post(request)
        from django.contrib.messages import get_messages
        return [(m.level_tag, str(m)) for m in get_messages(request)]

    def test_confirmation_refuse_une_cle_absente_des_correspondances_proposees(self):
        """Une clé qui n'est pas dans les correspondances en session ne doit jamais être
        liée : formulaire périmé (recherche relancée dans un autre onglet) ou requête
        envoyée directement. Sans ce contrôle, n'importe quel couple compte ENT / fiche
        pouvait être lié en rejouant un POST, sans aucune corroboration."""
        famille = Famille.objects.create(nom="FORGE")
        cible = Individu.objects.create(nom="FORGE", prenom="Cible", civilite=4)
        Rattachement.objects.create(individu=cible, famille=famille, categorie=2, titulaire=False)

        # Session vide de toute proposition : la clé est forgée de toutes pièces
        msgs = self._confirmer([f"ENT-FORGE|{cible.pk}"], [])

        cible.refresh_from_db()
        self.assertIsNone(
            cible.ent_id,
            "Une clé jamais proposée a quand même été liée - la confirmation fait "
            "confiance au navigateur au lieu de revalider côté serveur.",
        )
        self.assertTrue([m for niveau, m in msgs if "ne fait pas partie" in m])

    def test_confirmation_refuse_une_ligne_ecartee_pour_collision(self):
        """Cas concret du contrôle ci-dessus : une ligne retirée des propositions parce
        qu'elle est en collision avec une autre famille (ou écartée par le départage) ne
        doit pas redevenir liable en rejouant l'ancien formulaire."""
        famille_gagnante = Famille.objects.create(nom="REJOUE A")
        gagnant = Individu.objects.create(nom="REJOUE", prenom="Julia", civilite=4)
        Rattachement.objects.create(individu=gagnant, famille=famille_gagnante, categorie=2, titulaire=False)

        famille_ecartee = Famille.objects.create(nom="REJOUE C")
        ecarte = Individu.objects.create(nom="REJOUE", prenom="Julia", civilite=4)
        Rattachement.objects.create(individu=ecarte, famille=famille_ecartee, categorie=2, titulaire=False)

        # La session ne contient que la ligne retenue - celle de la famille écartée n'y est
        # plus, exactement comme après une détection de collision ou un départage.
        session = [{
            "famille_id": famille_gagnante.pk, "famille_nom": famille_gagnante.nom,
            "lignes": [{"cle": f"ENT-J|{gagnant.pk}", "nom_ent": "Julia REJOUE",
                        "nom_individu": str(gagnant), "role": "Enfant"}],
        }]

        # L'agent rejoue l'ancien formulaire, qui contenait encore la ligne écartée
        self._confirmer([f"ENT-J|{ecarte.pk}"], session)

        ecarte.refresh_from_db()
        self.assertIsNone(
            ecarte.ent_id,
            "La fiche écartée pour collision a été liée via un POST rejoué - c'est "
            "précisément la liaison ambiguë que la détection refusait de proposer.",
        )

    def test_confirmation_liste_les_lignes_ignorees_avec_leur_raison(self):
        """Une ligne cochée qui ne peut pas être liée ne doit jamais être ignorée en
        silence : le message doit nommer la personne et donner la raison précise."""
        famille = Famille.objects.create(nom="CONFIRM")
        ok = Individu.objects.create(nom="CONFIRM", prenom="Reussite", civilite=4)
        deja = Individu.objects.create(nom="CONFIRM", prenom="DejaLie", civilite=4, ent_id="ENT-DEJA")
        # Un autre individu détient déjà le compte visé par la 3e ligne
        Individu.objects.create(nom="AUTRE", prenom="Detenteur", civilite=1, ent_id="ENT-PRIS")
        convoite = Individu.objects.create(nom="CONFIRM", prenom="ComptePris", civilite=4)
        for ind in (ok, deja, convoite):
            Rattachement.objects.create(individu=ind, famille=famille, categorie=2, titulaire=False)

        lignes = [
            {"cle": f"ENT-OK|{ok.pk}", "nom_ent": "Reussite", "nom_individu": str(ok), "role": "Enfant"},
            {"cle": f"ENT-AUTRE|{deja.pk}", "nom_ent": "DejaLie", "nom_individu": str(deja), "role": "Enfant"},
            {"cle": f"ENT-PRIS|{convoite.pk}", "nom_ent": "ComptePris", "nom_individu": str(convoite), "role": "Enfant"},
            {"cle": f"ENT-FANTOME|999999", "nom_ent": "Fantome", "nom_individu": "CONFIRM Fantome", "role": "Enfant"},
        ]
        groupes = [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": lignes}]

        msgs = self._confirmer([l["cle"] for l in lignes], groupes)
        texte = " || ".join(t for _, t in msgs)

        # 1 seule réussite
        ok.refresh_from_db()
        self.assertEqual(ok.ent_id, "ENT-OK")
        self.assertIn("1 individu(s) lié(s)", texte)

        # ... et les 3 échecs sont nommés avec leur raison
        self.assertIn("3 liaison(s) non effectuée(s)", texte,
                      "Les lignes ignorées ne sont pas signalées à l'agent.")
        self.assertIn(str(deja), texte)
        self.assertIn("déjà lié", texte)
        self.assertIn(str(convoite), texte)
        self.assertIn("Detenteur", texte)          # nomme QUI détient le compte
        self.assertIn("n'existe plus", texte)      # la ligne fantôme

        # les échecs ne doivent pas être comptés comme des réussites
        deja.refresh_from_db()
        self.assertEqual(deja.ent_id, "ENT-DEJA")

    def test_confirmation_ligne_deja_liee_ailleurs_nest_pas_une_erreur(self):
        """Cas fréquent : l'agent a déjà fait la liaison via le bouton "Vérifier/lier" (qui
        ouvre un onglet), puis confirme la ligne restée à l'écran. Le résultat voulu étant
        atteint, ça ne doit pas être annoncé comme un échec."""
        famille = Famille.objects.create(nom="DEJAFAIT")
        ind = Individu.objects.create(nom="DEJAFAIT", prenom="Lucas", civilite=4, ent_id="ENT-L")
        Rattachement.objects.create(individu=ind, famille=famille, categorie=2, titulaire=False)
        lignes = [{"cle": f"ENT-L|{ind.pk}", "nom_ent": "Lucas", "nom_individu": str(ind), "role": "Enfant"}]

        msgs = self._confirmer([lignes[0]["cle"]], [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": lignes}])
        niveaux = [n for n, _ in msgs]
        texte = " || ".join(t for _, t in msgs)

        self.assertNotIn("warning", niveaux,
                         "Une liaison déjà en place à l'identique est signalée comme un échec.")
        self.assertIn("déjà en place", texte)
        self.assertIn(str(ind), texte)

    def test_confirmation_sans_echec_ne_produit_pas_d_avertissement(self):
        """Non-régression : quand tout passe, aucun message d'avertissement parasite."""
        famille = Famille.objects.create(nom="CONFIRM2")
        ind = Individu.objects.create(nom="CONFIRM2", prenom="Ok", civilite=4)
        Rattachement.objects.create(individu=ind, famille=famille, categorie=2, titulaire=False)
        lignes = [{"cle": f"ENT-OK2|{ind.pk}", "nom_ent": "Ok", "nom_individu": str(ind), "role": "Enfant"}]

        msgs = self._confirmer([lignes[0]["cle"]], [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": lignes}])
        niveaux = [n for n, _ in msgs]
        self.assertIn("success", niveaux)
        self.assertNotIn("warning", niveaux)

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
        request.user = Utilisateur.objects.create_user(username="agent_test_regle8c")

        vue = PreLiaisonEnt()
        vue.request = request
        vue.kwargs = {}
        vue.post(request)

        enfant.refresh_from_db()
        self.assertEqual(
            enfant.ent_id, "ANCIEN-COMPTE",
            "L'ent_id existant a été écrasé par la confirmation de pré-liaison.",
        )

    # ------------------------------------------------- trace ent_lie_par / ent_lie_le

    def test_confirmation_preliaison_enregistre_lagent_pas_auto(self):
        """L'agent a coché explicitement cette ligne avant de confirmer - ce n'est pas
        un import en masse sans revue, donc ent_lie_par doit être son identifiant, pas
        "auto"."""
        famille = Famille.objects.create(nom="TRACECONFIRM")
        enfant = Individu.objects.create(nom="TRACECONFIRM", prenom="Julia", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        lignes = [{"cle": f"ENT-J|{enfant.pk}", "nom_ent": "Julia", "nom_individu": str(enfant), "role": "Enfant"}]

        self._confirmer([lignes[0]["cle"]], [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": lignes}])

        enfant.refresh_from_db()
        self.assertEqual(enfant.ent_id, "ENT-J")
        self.assertNotEqual(enfant.ent_lie_par, "auto")
        self.assertTrue(enfant.ent_lie_par.startswith("agent_test_"))
        self.assertIsNotNone(enfant.ent_lie_le)

    def test_confirmation_preliaison_cree_un_seul_log_de_lancement(self):
        """Un seul log Historique pour tout le clic "Confirmer", pas une ligne par
        enfant lié - le détail par enfant est déjà tracé sur chaque fiche."""
        famille = Famille.objects.create(nom="TRACELOG")
        enfants = [Individu.objects.create(nom="TRACELOG", prenom=f"Enfant{i}", civilite=4) for i in range(3)]
        for e in enfants:
            Rattachement.objects.create(individu=e, famille=famille, categorie=2, titulaire=False)
        lignes = [{"cle": f"ENT-{i}|{e.pk}", "nom_ent": f"Enfant{i}", "nom_individu": str(e), "role": "Enfant"} for i, e in enumerate(enfants)]

        avant = Historique.objects.count()
        self._confirmer([l["cle"] for l in lignes], [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": lignes}])

        nouveaux = Historique.objects.filter(titre="Confirmation de liaisons en pré-liaison ENT")
        self.assertEqual(
            nouveaux.count(), 1,
            "Il devrait y avoir un seul log de lancement, pas un par enfant lié.",
        )
        self.assertIn("3 liaison(s)", nouveaux.first().detail)


class TestImporterEleveEnt(TestCase):
    """Tests directs de _importer_eleve_ent (logique partagée entre l'import unitaire et
    l'import en masse) - appelée directement, sans passer par les vues, avec des données
    ENT déjà fournies (pas d'appel réseau)."""

    def _eleve_data(self, ent_id="ENT-NOUVEAU"):
        return {
            "id": ent_id,
            "type": "Student",
            "firstName": "Nouveau",
            "lastName": "TESTIMPORT",
            "birthDate": "2015-06-01",
            "parents": [],
        }

    def test_import_unitaire_enregistre_lagent(self):
        """Import via l'écran unitaire (agent qui choisit et revoit une famille précise
        à l'écran) : ent_lie_par doit être l'identifiant de l'agent."""
        resultat = _importer_eleve_ent("ENT-UNITAIRE", eleve_data=self._eleve_data("ENT-UNITAIRE"), lie_par="agent_import_test")

        self.assertEqual(resultat["statut"], "importe")
        eleve = Individu.objects.get(ent_id="ENT-UNITAIRE")
        self.assertEqual(eleve.ent_lie_par, "agent_import_test")
        self.assertIsNotNone(eleve.ent_lie_le)

    def test_import_masse_enregistre_auto(self):
        """Import en masse (aucune revue individuelle par élève) : ent_lie_par doit être
        le tag "auto", pas l'agent qui a lancé l'action globale."""
        resultat = _importer_eleve_ent("ENT-MASSE", eleve_data=self._eleve_data("ENT-MASSE"), lie_par="auto")

        self.assertEqual(resultat["statut"], "importe")
        eleve = Individu.objects.get(ent_id="ENT-MASSE")
        self.assertEqual(eleve.ent_lie_par, "auto")
        self.assertIsNotNone(eleve.ent_lie_le)

    def test_import_sans_lie_par_ne_renseigne_rien(self):
        """Non-régression : si aucun lie_par n'est fourni (défaut), les champs restent
        vides plutôt que de mettre une valeur inventée."""
        resultat = _importer_eleve_ent("ENT-SANSTRACE", eleve_data=self._eleve_data("ENT-SANSTRACE"))

        self.assertEqual(resultat["statut"], "importe")
        eleve = Individu.objects.get(ent_id="ENT-SANSTRACE")
        self.assertIsNone(eleve.ent_lie_par)
        self.assertIsNone(eleve.ent_lie_le)


class TestImporterFamilleEntEcoleNonReconnue(TestCase):
    """Tests de l'écran 'Importer une famille depuis l'ENT' (recherche unitaire) - règle du
    masquage des écoles non reconnues. Décision d'équipe (CR du 17/07) :
    "on ne doit même pas voir les enfants qui appartiennent a d'autres écoles" - déjà respectée
    par l'import en masse (ImporterEnMasseEnt), mais cet écran-ci se contentait jusqu'ici de
    bloquer le bouton d'import en affichant quand même la fiche (nom, école, parents...), ce qui
    revient déjà à remonter l'information que la règle interdit."""

    def _lancer_recherche(self, eleves_ent):
        """eleves_ent : liste de dicts complets façon get_user (id, type, structures...).
        search_by_name renvoie la version brève (id/type) que l'ENT donne réellement, get_user
        renvoie le détail complet - reproduit la vraie séparation en 2 appels du code."""
        briefs = [{"id": e["id"], "type": e.get("type", "Student")} for e in eleves_ent]
        par_id = {e["id"]: e for e in eleves_ent}

        request = RequestFactory().post("/", {"action": "rechercher", "first_name": "Test", "last_name": "Test"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()

        with patch("fiche_famille.views.famille_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_famille.views.famille_ent.search_by_name", return_value=briefs), \
             patch("fiche_famille.views.famille_ent.get_user", side_effect=lambda ent_id: par_id.get(ent_id)), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            ImporterFamilleEnt()._effectuer_recherche(request, "Test", "Test")

        return (
            request.session.get("ent_resultats"),
            request.session.get("ent_nb_masques_ecole_inconnue", 0),
            request.session.get("ent_erreur"),
        )

    @staticmethod
    def _eleve(ent_id, prenom, nom, ecole_nom, ecole_uai, ecole_ent_id):
        return {
            "id": ent_id, "type": "Student", "firstName": prenom, "lastName": nom,
            "structures": [{"name": ecole_nom, "uai": ecole_uai, "id": ecole_ent_id}],
            "parents": [],
        }

    def test_eleve_ecole_reconnue_est_affiche(self):
        Ecole.objects.create(nom="École Test", uai="UAI999", ent_id="ENT-ECOLE-1")
        eleve = self._eleve("ENT-E1", "Alice", "DUPONT", "École Test", "UAI999", "ENT-ECOLE-1")

        resultats, nb_masques, erreur = self._lancer_recherche([eleve])

        self.assertEqual(nb_masques, 0)
        self.assertTrue(resultats)
        self.assertEqual(resultats[0]["id"], "ENT-E1")

    def test_eleve_ecole_non_reconnue_est_masque_pas_juste_bloque(self):
        """Le point signalé par l'équipe : l'élève ne doit même pas apparaître, pas juste avoir
        son bouton d'import désactivé avec un message rouge."""
        eleve = self._eleve("ENT-E2", "Bob", "MARTIN", "Ecole Inconnue", "UAI000", "ENT-ECOLE-X")

        resultats, nb_masques, erreur = self._lancer_recherche([eleve])

        self.assertEqual(nb_masques, 1)
        self.assertFalse(
            resultats,
            "L'élève d'une école non reconnue apparaît quand même dans les résultats - "
            "il devrait être masqué entièrement, comme le fait déjà l'import en masse.",
        )

    def test_message_quand_tout_est_masque_ne_suggere_pas_de_creer_la_famille(self):
        """Si tous les résultats sont masqués, le message ne doit pas laisser croire que la
        famille n'existe pas dans l'ENT - "Aucun résultat"/"Aucune famille" déclenche à
        l'écran une suggestion de création manuelle, qui ferait un doublon dès que l'école
        sera importée."""
        eleve = self._eleve("ENT-E3", "Chloe", "LEGRAND", "Ecole Inconnue", "UAI000", "ENT-ECOLE-X")

        resultats, nb_masques, erreur = self._lancer_recherche([eleve])

        self.assertIsNone(resultats)
        self.assertIn("masqué", erreur)
        self.assertNotIn("Aucune famille", erreur)
        self.assertNotIn("Aucun résultat", erreur)

    def test_cas_mixte_seul_lenfant_dune_ecole_reconnue_reste_affiche(self):
        Ecole.objects.create(nom="École Test", uai="UAI999", ent_id="ENT-ECOLE-1")
        eleve_ok = self._eleve("ENT-OK", "OK", "PERSON", "École Test", "UAI999", "ENT-ECOLE-1")
        eleve_masque = self._eleve("ENT-KO", "KO", "PERSON", "Ecole Inconnue", "UAI000", "ENT-ECOLE-X")

        resultats, nb_masques, erreur = self._lancer_recherche([eleve_ok, eleve_masque])

        self.assertEqual(nb_masques, 1)
        ids = [r["id"] for r in resultats]
        self.assertIn("ENT-OK", ids)
        self.assertNotIn("ENT-KO", ids)


class TestReattributionPrestation(TestCase):
    """Le bouton "Réattribuer une prestation" (ReattribuerPrestation) sert à corriger
    manuellement une prestation restée ambiguë après une séparation de famille (enfant
    partagé, aucun titulaire clair). Doit déplacer aussi les déductions (aides financières)
    rattachées à cette prestation - sinon prestation et aide se retrouvent dans 2 familles
    différentes, comme si elles n'avaient plus rien à voir l'une avec l'autre."""

    def _reattribuer(self, prestation, famille_origine, famille_cible):
        request = RequestFactory().post("/", {"idfamille_cible": famille_cible.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = ReattribuerPrestation()
        vue.request = request
        vue.kwargs = {"idfamille": famille_origine.pk, "pk": prestation.pk}
        vue.post(request)

    def test_reattribution_deplace_aussi_la_deduction_associee(self):
        famille_origine = Famille.objects.create(nom="ORIGINE")
        famille_cible = Famille.objects.create(nom="CIBLE")
        enfant = Individu.objects.create(nom="PARTAGE", prenom="Enfant", civilite=4)
        # L'enfant doit être rattaché aux deux familles pour que la réattribution soit
        # autorisée (vérification de sécurité côté serveur, cas d'un enfant partagé).
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        prestation = Prestation.objects.create(
            date=date(2026, 9, 1), label="Garderie", montant=20, famille=famille_origine, individu=enfant,
        )
        deduction = Deduction.objects.create(
            prestation=prestation, famille=famille_origine, date=date(2026, 9, 1), montant=5, label="Aide CAF",
        )

        self._reattribuer(prestation, famille_origine, famille_cible)

        prestation.refresh_from_db()
        deduction.refresh_from_db()
        self.assertEqual(prestation.famille_id, famille_cible.pk)
        self.assertEqual(
            deduction.famille_id, famille_cible.pk,
            "La déduction n'a pas suivi sa prestation lors de la réattribution manuelle - "
            "elle reste dans l'ancienne famille alors que sa prestation est partie.",
        )

    def test_reattribution_sans_deduction_ne_plante_pas(self):
        """Non-régression : une prestation sans aucune déduction associée doit toujours
        pouvoir être réattribuée normalement."""
        famille_origine = Famille.objects.create(nom="ORIGINE2")
        famille_cible = Famille.objects.create(nom="CIBLE2")
        enfant = Individu.objects.create(nom="SANSAIDE", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        prestation = Prestation.objects.create(
            date=date(2026, 9, 1), label="Piscine", montant=15, famille=famille_origine, individu=enfant,
        )

        self._reattribuer(prestation, famille_origine, famille_cible)

        prestation.refresh_from_db()
        self.assertEqual(prestation.famille_id, famille_cible.pk)

    def test_reattribution_deplace_aussi_la_cotisation_liee(self):
        """Une Cotisation (adhésion) a un lien un-pour-un avec sa prestation - même
        problème que la déduction : sans correctif, la carte d'adhérent reste dans
        l'ancienne famille pendant que la prestation qui la finance part dans l'autre."""
        famille_origine = Famille.objects.create(nom="ORIGINE3")
        famille_cible = Famille.objects.create(nom="CIBLE3")
        enfant = Individu.objects.create(nom="ADHERENT", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        prestation = Prestation.objects.create(
            date=date(2026, 9, 1), label="Adhésion Ados Loisirs", montant=25,
            famille=famille_origine, individu=enfant,
        )
        type_cotisation = TypeCotisation.objects.create(nom="Ados Loisirs")
        unite_cotisation = UniteCotisation.objects.create(type_cotisation=type_cotisation, nom="Année", montant=25)
        cotisation = Cotisation.objects.create(
            famille=famille_origine, individu=enfant, type_cotisation=type_cotisation, unite_cotisation=unite_cotisation,
            date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31), prestation=prestation,
        )

        self._reattribuer(prestation, famille_origine, famille_cible)

        prestation.refresh_from_db()
        cotisation.refresh_from_db()
        self.assertEqual(prestation.famille_id, famille_cible.pk)
        self.assertEqual(
            cotisation.famille_id, famille_cible.pk,
            "La cotisation n'a pas suivi sa prestation lors de la réattribution manuelle - "
            "la carte d'adhérent reste dans l'ancienne famille alors que sa prestation est partie.",
        )

    def test_reattribution_trace_lagent_dans_lhistorique(self):
        """Traçabilité (exigence de sécurité/légale, même principe que pour les liaisons
        ENT) : réattribuer une prestation déplace de l'argent d'une famille à une autre -
        il faut pouvoir remonter à l'agent qui l'a fait."""
        famille_origine = Famille.objects.create(nom="TRACE ORIGINE")
        famille_cible = Famille.objects.create(nom="TRACE CIBLE")
        enfant = Individu.objects.create(nom="TRACE", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)

        prestation = Prestation.objects.create(
            date=date(2026, 9, 1), label="Garderie", montant=20, famille=famille_origine, individu=enfant,
        )
        Deduction.objects.create(prestation=prestation, famille=famille_origine, date=date(2026, 9, 1), montant=5, label="Aide CAF")

        self._reattribuer(prestation, famille_origine, famille_cible)

        log = Historique.objects.filter(individu_id=enfant.pk, titre__icontains="Réattribution").first()
        self.assertIsNotNone(log, "Aucune trace créée pour la réattribution de la prestation.")
        self.assertIn("TRACE ORIGINE", log.detail)
        self.assertIn("TRACE CIBLE", log.detail)
        self.assertIn("Garderie", log.detail)
        self.assertIn("déduction", log.detail.lower())
        self.assertIsNotNone(log.utilisateur, "La trace ne dit pas quel agent a fait la réattribution.")


class TestMigrationInscriptionSeparation(TestCase):
    """L'inscription d'un enfant partagé doit suivre la même règle que sa prestation lors
    d'une séparation manuelle : suit le parent qui part seulement si celui-ci est l'unique
    titulaire du dossier (sinon ambiguë, reste par défaut - à réattribuer manuellement)."""

    def _creer_inscription(self, famille, individu):
        structure = Structure.objects.create(nom="Structure Test")
        activite = Activite.objects.create(nom="Cantine", abrege="CANT", structure=structure)
        groupe = Groupe.objects.create(activite=activite, nom="Groupe A", ordre=1)
        categorie_tarif = CategorieTarif.objects.create(activite=activite, nom="Standard")
        return Inscription.objects.create(
            individu=individu, famille=famille, activite=activite, groupe=groupe,
            categorie_tarif=categorie_tarif, date_debut=date(2026, 9, 1),
        )

    def _separer(self, famille, id_parent):
        request = RequestFactory().post("/", {"id_parent": id_parent})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = SeparerFamille()
        vue.request = request
        vue.kwargs = {"idfamille": famille.pk}
        vue.post(request)

    def test_inscription_enfant_suit_le_parent_titulaire_unique(self):
        famille = Famille.objects.create(nom="INSCR TITULAIRE UNIQUE")
        parent = Individu.objects.create(nom="MOREAU", prenom="Marc", civilite=1)
        autre_parent = Individu.objects.create(nom="MOREAU", prenom="Sophie", civilite=3)
        enfant = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        inscription = self._creer_inscription(famille, enfant)

        self._separer(famille, parent.pk)

        inscription.refresh_from_db()
        self.assertNotEqual(
            inscription.famille_id, famille.pk,
            "L'inscription de l'enfant n'a pas suivi le parent, alors qu'il est l'unique "
            "titulaire du dossier - même règle que pour les prestations.",
        )

    def test_inscription_enfant_reste_ambigue_si_deux_titulaires(self):
        famille = Famille.objects.create(nom="INSCR DEUX TITULAIRES")
        parent = Individu.objects.create(nom="MOREAU", prenom="Marc", civilite=1)
        autre_parent = Individu.objects.create(nom="MOREAU", prenom="Sophie", civilite=3)
        enfant = Individu.objects.create(nom="MOREAU", prenom="Lea", civilite=4)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        inscription = self._creer_inscription(famille, enfant)

        self._separer(famille, parent.pk)

        inscription.refresh_from_db()
        self.assertEqual(
            inscription.famille_id, famille.pk,
            "L'inscription de l'enfant a migré alors qu'aucun titulaire clair ne permettait "
            "de trancher (2 titulaires) - elle devrait rester ambiguë, comme une prestation.",
        )

    def test_inscription_du_parent_lui_meme_suit_toujours(self):
        """Non-régression : l'inscription du parent qui part lui-même doit toujours suivre,
        peu importe le nombre de titulaires - comportement inchangé."""
        famille = Famille.objects.create(nom="INSCR PARENT LUI MEME")
        parent = Individu.objects.create(nom="MOREAU", prenom="Marc", civilite=1)
        autre_parent = Individu.objects.create(nom="MOREAU", prenom="Sophie", civilite=3)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=True)

        inscription = self._creer_inscription(famille, parent)

        self._separer(famille, parent.pk)

        inscription.refresh_from_db()
        self.assertNotEqual(inscription.famille_id, famille.pk)


class TestFusionnerFamillesHistorique(TestCase):
    """La fusion supprime la famille source (nom, ID) sans laisser de trace ailleurs -
    action critique puisque factures/prestations/règlements/payeur des deux familles
    sont regroupés sans distinction possible après coup. Un Historique doit être créé,
    sur la famille cible, avant que la famille source ne disparaisse."""

    def _fusionner(self, famille_cible, famille_source):
        request = RequestFactory().post("/", {"idfamille_source": famille_source.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = FusionnerFamilles()
        vue.request = request
        vue.kwargs = {"idfamille": famille_cible.pk}
        vue.post(request)

    def test_historique_garde_trace_de_la_fusion(self):
        famille_cible = Famille.objects.create(nom="FUSION CIBLE")
        famille_source = Famille.objects.create(nom="FUSION SOURCE")
        id_source = famille_source.pk
        enfant = Individu.objects.create(nom="FUSION", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille_source, categorie=2, titulaire=False)

        self._fusionner(famille_cible, famille_source)

        self.assertFalse(Famille.objects.filter(pk=id_source).exists(), "La famille source aurait dû être supprimée.")

        historique = Historique.objects.filter(titre="Fusion de familles", famille=famille_cible).order_by("-idaction").first()
        self.assertIsNotNone(historique, "Aucune trace de la fusion dans l'historique - action critique non tracée.")
        self.assertIn("FUSION SOURCE", historique.detail)
        self.assertIn(str(id_source), historique.detail)
        self.assertIn("FUSION CIBLE", historique.detail)
