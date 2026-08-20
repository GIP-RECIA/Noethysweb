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
from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware

from core.models import (
    Activite, Assurance, Assureur, CategorieTarif, Classe, ContactUrgence, Cotisation, Deduction,
    Destinataire, DestinataireSMS, Ecole, Facture, Famille, Groupe, Historique, Individu, Inscription,
    Mandat, Note, Payeur, Piece, PortailRenseignement, Prestation, QuestionnaireQuestion,
    QuestionnaireReponse, Rattachement, Scolarite, Sondage, SondageRepondant, Structure,
    TypeCotisation, UniteCotisation, Utilisateur,
)
from fiche_famille.views.famille_ent import FusionnerFamilles, ImporterEnMasseEnt, ImporterFamilleEnt, PreLiaisonEnt, SeparerFamille, _adresses_differentes, _importer_eleve_ent
from fiche_famille.views.famille_ent_synchro import ListeSynchro
from fiche_famille.views.famille_prestations import ReattribuerPrestation


def _fusionner(famille_cible, famille_source, data=None):
    """Appelle FusionnerFamilles.post() directement (hors client Django), comme
    fait le reste du fichier pour les vues à base de classe."""
    payload = {"idfamille_source": famille_source.pk}
    if data:
        payload = data
    request = RequestFactory().post("/", payload)
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

    vue = FusionnerFamilles()
    vue.request = request
    vue.kwargs = {"idfamille": famille_cible.pk}
    return vue.post(request)


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

    # ------------------------------------------------------------------ cas restants

    def test_aucun_resultat_bascule_en_non_resolu(self):
        famille = Famille.objects.create(nom="A51")
        enfant = Individu.objects.create(nom="A51", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)

        groupes, non_resolus = self._lancer_recherche({"Enfant": lambda: []})

        self.assertFalse(self._cles_proposees(groupes))
        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons)
        self.assertIn("orthographié", raisons[0])

    def test_plusieurs_candidats_corroborent_reste_ambigu(self):
        """Cas réel documenté du projet (ex: 2 "Julia" différentes côté ENT dont le nom
        de parent correspond par coïncidence à la même famille Noethys)."""
        famille = Famille.objects.create(nom="A53")
        enfant = Individu.objects.create(nom="A53", prenom="Julia", civilite=4)
        parent = Individu.objects.create(nom="A53", prenom="Gabriel", civilite=1)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        def deux_candidats():
            return [
                _resultat_eleve("ENT-J1", "A53", "Julia", parents=[{"firstName": "Gabriel", "lastName": "A53", "id": "ENT-G1"}]),
                _resultat_eleve("ENT-J2", "A53", "Julia", parents=[{"firstName": "Gabriel", "lastName": "A53", "id": "ENT-G2"}]),
            ]
        groupes, non_resolus = self._lancer_recherche({"Julia": deux_candidats})

        self.assertFalse(self._cles_proposees(groupes))
        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons)
        self.assertIn("ambigu", raisons[0].lower())

    def test_un_seul_corrobore_parmi_plusieurs_est_propose(self):
        famille = Famille.objects.create(nom="A54")
        enfant = Individu.objects.create(nom="A54", prenom="Julia", civilite=4)
        parent = Individu.objects.create(nom="A54", prenom="Gabriel", civilite=1)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        def deux_candidats():
            return [
                _resultat_eleve("ENT-J1B", "A54", "Julia", parents=[{"firstName": "Gabriel", "lastName": "A54", "id": "ENT-G1B"}]),
                _resultat_eleve("ENT-J2B", "A54", "Julia", parents=[{"firstName": "Inconnu", "lastName": "ZZZAUCUNMATCH", "id": "ENT-X"}]),
            ]
        groupes, non_resolus = self._lancer_recherche({"Julia": deux_candidats})

        self.assertIn(f"ENT-J1B|{enfant.pk}", self._cles_proposees(groupes))

    def test_date_contredit_message_precis_en_preliaison(self):
        """Le message doit citer les 2 dates (pas "aucun parent ne correspond", qui
        serait faux puisqu'un nom corrobore bien)."""
        famille = Famille.objects.create(nom="A55")
        enfant = Individu.objects.create(nom="A55", prenom="Enfant", civilite=4, date_naiss=date(2010, 1, 1))
        parent = Individu.objects.create(nom="A55", prenom="Papa", civilite=1)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)

        def candidat():
            return [_resultat_eleve("ENT-DATEKO", "A55", "Enfant", birth="2011-06-01", parents=[{"firstName": "Papa", "lastName": "A55", "id": "ENT-PAPA"}])]
        groupes, non_resolus = self._lancer_recherche({"Enfant": candidat})

        raisons = [p["raison"] for g in non_resolus if g["famille_id"] == famille.pk for p in g["personnes"]]
        self.assertTrue(raisons)
        self.assertIn("date de naissance", raisons[0])
        self.assertNotIn("aucun parent ne correspond", raisons[0])

    def test_confirmation_fiche_supprimee_entre_temps_est_signalee(self):
        famille = Famille.objects.create(nom="A519")
        enfant = Individu.objects.create(nom="A519", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        cle = f"ENT-A519|{enfant.pk}"
        session = [{"famille_id": famille.pk, "famille_nom": famille.nom, "lignes": [{"cle": cle, "nom_ent": "Enfant A519", "nom_individu": str(enfant), "role": "Enfant"}]}]

        enfant.delete()

        msgs = self._confirmer([cle], session)

        self.assertTrue([m for niveau, m in msgs if "n'existe plus" in m])

    def test_beaucoup_de_lignes_est_plafonne_a_10(self):
        cles = [f"ENT-PLAF{i}|9990{i}" for i in range(12)]

        msgs = self._confirmer(cles, [])

        detail = next(m for niveau, m in msgs if "liaison(s) non effectuée" in m)
        self.assertIn("et 2 autre(s)", detail)

    def test_session_ancien_format_ne_plante_pas(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session[PreLiaisonEnt.SESSION_KEY] = ["ancien", "format", "liste"]
        request.session.save()
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = PreLiaisonEnt()
        vue.request = request
        vue.kwargs = {}
        context = vue.get_context_data()

        self.assertEqual(context["groupes"], [])
        self.assertEqual(context["non_resolus"], [])


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


class TestImporterEleveEntErreurTechnique(TestCase):
    """Le except attrape-tout de _importer_eleve_ent ne doit jamais montrer le texte brut
    d'une exception Python à l'agent (ex: "list index out of range", vu avec le bug du
    parent Contact avant son fix) - message générique à l'écran, détail complet dans les
    logs serveur pour pouvoir enquêter."""

    @staticmethod
    def _eleve_data(ent_id):
        return {"id": ent_id, "type": "Student", "firstName": "Crash", "lastName": "TEST", "birthDate": "2015-06-01", "parents": []}

    def test_message_generique_pas_de_texte_technique_brut(self):
        with patch("core.models.Individu.save", side_effect=RuntimeError("boom technique interne")):
            resultat = _importer_eleve_ent("ENT-CRASH1", eleve_data=self._eleve_data("ENT-CRASH1"))

        self.assertEqual(resultat["statut"], "erreur")
        self.assertNotIn("boom technique interne", resultat["message"])
        self.assertIn("contactez le support", resultat["message"])

    def test_exception_est_loguee_pour_enqueter(self):
        with patch("core.models.Individu.save", side_effect=RuntimeError("boom technique interne")):
            with self.assertLogs("fiche_famille.views.famille_ent", level="ERROR") as cm:
                _importer_eleve_ent("ENT-CRASH2", eleve_data=self._eleve_data("ENT-CRASH2"))

        self.assertTrue(any("boom technique interne" in msg for msg in cm.output))


class TestImporterFamilleEntRecherche(TestCase):
    """Cas de ImporterFamilleEnt.post()/_effectuer_recherche()/_importer() jamais testés
    jusqu'ici : validation du formulaire, connexion, panne, résultat parent, revérification
    de l'école au clic, élève introuvable."""

    def _post_rechercher(self, last_name, first_name, get_headers_ret="ok", search_ret=None):
        request = RequestFactory().post("/", {"action": "rechercher", "last_name": last_name, "first_name": first_name})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        headers_value = None if get_headers_ret is None else {"Authorization": "Bearer test"}
        with patch("fiche_famille.views.famille_ent.get_headers", return_value=headers_value), \
             patch("fiche_famille.views.famille_ent.search_by_name", return_value=search_ret):
            ImporterFamilleEnt().post(request)
        return request.session

    def test_prenom_ou_nom_vide(self):
        session = self._post_rechercher("", "Test")
        self.assertEqual(session.get("ent_erreur"), "Veuillez saisir le prénom ET le nom.")

    def test_connexion_impossible(self):
        session = self._post_rechercher("X", "Y", get_headers_ret=None)
        self.assertIn("Impossible de se connecter", session.get("ent_erreur"))

    def test_panne_pendant_la_recherche(self):
        """search_by_name renvoie None (panne en cours d'appel) - distinct du cas
        get_headers()=None (panne détectée avant même d'essayer)."""
        session = self._post_rechercher("X", "Y", search_ret=None)
        self.assertIn("échoué", session.get("ent_erreur"))

    def test_aucun_resultat(self):
        session = self._post_rechercher("X", "Y", search_ret=[])
        self.assertIn("Aucun résultat", session.get("ent_erreur"))

    def test_recherche_par_parent_remonte_a_ses_enfants(self):
        """Chercher un parent (Relative) doit proposer ses enfants, pas rien."""
        par_id = {
            "ENT-PARENT": {"id": "ENT-PARENT", "type": "Relative", "children": [{"id": "ENT-ENFANT"}]},
            "ENT-ENFANT": {"id": "ENT-ENFANT", "type": "Student", "firstName": "XE", "lastName": "TESTPARENT", "parents": []},
        }
        request = RequestFactory().post("/", {"action": "rechercher", "last_name": "TESTPARENT", "first_name": "XP"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        with patch("fiche_famille.views.famille_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_famille.views.famille_ent.search_by_name", return_value=[{"id": "ENT-PARENT", "type": "Relative"}]), \
             patch("fiche_famille.views.famille_ent.get_user", side_effect=lambda ent_id: par_id.get(ent_id)):
            ImporterFamilleEnt().post(request)

        resultats = request.session.get("ent_resultats")
        self.assertTrue(resultats, "La recherche par parent n'a remonté aucun enfant.")
        self.assertEqual(resultats[0]["id"], "ENT-ENFANT")

    def test_importer_refuse_si_ecole_non_reconnue_au_clic(self):
        eleve_data = {
            "id": "ENT-ECOLEKO", "type": "Student", "firstName": "XE", "lastName": "TESTECOLEKO",
            "structures": [{"name": "Ecole Jamais Connue Import", "uai": "UAI-X1", "id": "ENT-ECOLE-X1"}],
            "parents": [],
        }
        request = RequestFactory().post("/", {"action": "importer", "eleve_ent_id": "ENT-ECOLEKO"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        with patch("fiche_famille.views.famille_ent.get_user", return_value=eleve_data):
            ImporterFamilleEnt().post(request)

        self.assertFalse(
            Individu.objects.filter(ent_id="ENT-ECOLEKO").exists(),
            "L'élève a été importé alors que son école n'est pas reconnue - devrait être refusé au clic.",
        )

    def test_importer_erreur_si_donnees_elve_introuvables(self):
        request = RequestFactory().post("/", {"action": "importer", "eleve_ent_id": "ENT-INTROUVABLE"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        with patch("fiche_famille.views.famille_ent.get_user", return_value=None):
            ImporterFamilleEnt().post(request)

        self.assertFalse(Individu.objects.filter(ent_id="ENT-INTROUVABLE").exists())


class TestConstitutionFamilleImport(TestCase):
    """Cas de constitution de famille de _importer_eleve_ent jamais testés directement :
    même adresse, adresses différentes (déclenchement complet, pas juste la fonction de
    comparaison), un seul parent, aucun parent, scolarité, atomicité de la transaction."""

    def test_meme_adresse_cree_une_seule_famille(self):
        parents_cache = {
            "ENT-XP-A22": {"id": "ENT-XP-A22", "lastName": "XP", "firstName": "Papa", "address": "12 rue Test", "zipCode": "45000"},
            "ENT-XM-A22": {"id": "ENT-XM-A22", "lastName": "XM", "firstName": "Maman", "address": "12 rue Test", "zipCode": "45000"},
        }
        eleve_data = {"id": "ENT-XE-A22", "type": "Student", "firstName": "XE", "lastName": "TESTA22", "parents": [{"id": "ENT-XP-A22"}, {"id": "ENT-XM-A22"}]}

        resultat = _importer_eleve_ent("ENT-XE-A22", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertEqual(resultat["type"], "nouvelle_famille")
        self.assertEqual(Rattachement.objects.filter(famille_id=resultat["famille_id"], categorie=1, titulaire=True).count(), 2)

    def test_adresses_differentes_cree_deux_familles_separees(self):
        parents_cache = {
            "ENT-XP-A23": {"id": "ENT-XP-A23", "lastName": "XP", "firstName": "Papa", "address": "12 rue Test", "zipCode": "45000"},
            "ENT-XM-A23": {"id": "ENT-XM-A23", "lastName": "XM", "firstName": "Maman", "address": "9 avenue Autre", "zipCode": "45100"},
        }
        eleve_data = {"id": "ENT-XE-A23", "type": "Student", "firstName": "XE", "lastName": "TESTA23", "parents": [{"id": "ENT-XP-A23"}, {"id": "ENT-XM-A23"}]}

        resultat = _importer_eleve_ent("ENT-XE-A23", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertEqual(resultat["type"], "nouvelle_famille_separee")
        eleve = Individu.objects.get(ent_id="ENT-XE-A23")
        familles_ids = list(Rattachement.objects.filter(individu=eleve, categorie=2).values_list("famille_id", flat=True))
        self.assertEqual(len(familles_ids), 2, "l'enfant doit être rattaché aux 2 familles séparées")
        for famille_id in familles_ids:
            self.assertEqual(Famille.objects.get(pk=famille_id).mode_separation, "automatique")

    def test_un_seul_parent_connu_cree_famille_unique(self):
        parents_cache = {"ENT-XP-A25": {"id": "ENT-XP-A25", "lastName": "XP", "firstName": "Papa"}}
        eleve_data = {"id": "ENT-XE-A25", "type": "Student", "firstName": "XE", "lastName": "TESTA25", "parents": [{"id": "ENT-XP-A25"}]}

        resultat = _importer_eleve_ent("ENT-XE-A25", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertEqual(resultat["type"], "nouvelle_famille")
        self.assertEqual(Rattachement.objects.filter(famille_id=resultat["famille_id"], categorie=1).count(), 1)

    def test_aucun_parent_cree_famille_avec_enfant_seul(self):
        eleve_data = {"id": "ENT-XE-A26", "type": "Student", "firstName": "XE", "lastName": "TESTA26", "parents": []}

        resultat = _importer_eleve_ent("ENT-XE-A26", eleve_data=eleve_data, parents_cache={})

        self.assertEqual(resultat["statut"], "importe")
        self.assertEqual(Rattachement.objects.filter(famille_id=resultat["famille_id"], categorie=1).count(), 0)
        self.assertEqual(Rattachement.objects.filter(famille_id=resultat["famille_id"], categorie=2).count(), 1)

    def test_scolarite_creee_si_ecole_connue(self):
        Ecole.objects.create(nom="Ecole A27", ent_id="ENT-ECOLE-A27")
        eleve_data = {
            "id": "ENT-XE-A27", "type": "Student", "firstName": "XE", "lastName": "TESTA27", "parents": [],
            "structures": [{"name": "Ecole A27", "uai": None, "id": "ENT-ECOLE-A27"}],
        }

        _importer_eleve_ent("ENT-XE-A27", eleve_data=eleve_data, parents_cache={})

        eleve = Individu.objects.get(ent_id="ENT-XE-A27")
        self.assertTrue(Scolarite.objects.filter(individu=eleve).exists())

    def test_transaction_atomique_annule_tout_si_erreur(self):
        """Si l'import échoue en cours de route, rien ne doit rester en base - pas d'élève
        à moitié créé sans famille ni rattachement."""
        eleve_data = {"id": "ENT-XE-A210", "type": "Student", "firstName": "XE", "lastName": "TESTA210", "parents": []}

        with patch("fiche_famille.views.famille_ent.Rattachement.objects.create", side_effect=RuntimeError("boom")):
            resultat = _importer_eleve_ent("ENT-XE-A210", eleve_data=eleve_data, parents_cache={})

        self.assertEqual(resultat["statut"], "erreur")
        self.assertFalse(
            Individu.objects.filter(ent_id="ENT-XE-A210").exists(),
            "L'élève ne doit pas rester en base si la transaction a échoué en cours de route.",
        )


class TestImporterParentContactSeulement(TestCase):
    """Un parent déclaré par l'ENT peut déjà être connu dans Noethys uniquement comme
    Contact d'une autre famille (ex: un grand-parent qui aide à élever un autre petit-
    enfant), sans jamais être Représentant nulle part. Avant : le code supposait "déjà
    connu = représentant quelque part" et plantait (list index out of range) - ou, avec un
    fix naïf qui l'ignorerait simplement, créerait un DOUBLON (2 fiches, même ent_id) dans
    la branche "nouvelle famille"."""

    @staticmethod
    def _eleve_data(ent_id, parents):
        return {"id": ent_id, "type": "Student", "firstName": "XE", "lastName": "TESTCONTACT", "birthDate": "2015-06-01", "parents": parents}

    def _preparer_xgmp_contact(self, ent_id="ENT-XGMP"):
        famille_a = Famille.objects.create(nom="FAMILLE A")
        xgmp = Individu.objects.create(nom="XGMP", prenom="Mamie", civilite=3, ent_id=ent_id)
        Rattachement.objects.create(individu=xgmp, famille=famille_a, categorie=3, titulaire=False)
        return famille_a, xgmp

    def test_ne_plante_pas(self):
        self._preparer_xgmp_contact()
        parents_cache = {
            "ENT-XP": {"id": "ENT-XP", "lastName": "XP", "firstName": "Papa"},
            "ENT-XGMP": {"id": "ENT-XGMP", "lastName": "XGMP", "firstName": "Mamie"},
        }
        eleve_data = self._eleve_data("ENT-XE3", parents=[{"id": "ENT-XP"}, {"id": "ENT-XGMP"}])

        resultat = _importer_eleve_ent("ENT-XE3", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertEqual(resultat["statut"], "importe")

    def test_ne_duplique_pas_la_fiche_du_contact(self):
        self._preparer_xgmp_contact()
        parents_cache = {
            "ENT-XP": {"id": "ENT-XP", "lastName": "XP", "firstName": "Papa"},
            "ENT-XGMP": {"id": "ENT-XGMP", "lastName": "XGMP", "firstName": "Mamie"},
        }
        eleve_data = self._eleve_data("ENT-XE3B", parents=[{"id": "ENT-XP"}, {"id": "ENT-XGMP"}])

        _importer_eleve_ent("ENT-XE3B", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertEqual(
            Individu.objects.filter(ent_id="ENT-XGMP").count(), 1,
            "Le contact réutilisé ne doit jamais être dupliqué (2 fiches avec le même ent_id).",
        )

    def test_devient_representant_de_la_nouvelle_famille_sans_perdre_son_role_de_contact(self):
        famille_a, xgmp = self._preparer_xgmp_contact("ENT-XGMP2")
        parents_cache = {
            "ENT-XP2": {"id": "ENT-XP2", "lastName": "XP", "firstName": "Papa"},
            "ENT-XGMP2": {"id": "ENT-XGMP2", "lastName": "XGMP", "firstName": "Mamie"},
        }
        eleve_data = self._eleve_data("ENT-XE3C", parents=[{"id": "ENT-XP2"}, {"id": "ENT-XGMP2"}])

        resultat = _importer_eleve_ent("ENT-XE3C", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertTrue(
            Rattachement.objects.filter(individu=xgmp, famille=famille_a, categorie=3).exists(),
            "XGMP doit rester Contact de la famille A - son rôle là-bas ne doit pas changer.",
        )
        self.assertTrue(
            Rattachement.objects.filter(individu=xgmp, famille_id=resultat["famille_id"], categorie=1, titulaire=True).exists(),
            "XGMP doit devenir Représentante de la nouvelle famille de l'enfant importé.",
        )

    def test_message_mentionne_le_contact_reutilise(self):
        self._preparer_xgmp_contact("ENT-XGMP3")
        parents_cache = {
            "ENT-XP3": {"id": "ENT-XP3", "lastName": "XP", "firstName": "Papa"},
            "ENT-XGMP3": {"id": "ENT-XGMP3", "lastName": "XGMP", "firstName": "Mamie"},
        }
        eleve_data = self._eleve_data("ENT-XE3D", parents=[{"id": "ENT-XP3"}, {"id": "ENT-XGMP3"}])

        resultat = _importer_eleve_ent("ENT-XE3D", eleve_data=eleve_data, parents_cache=parents_cache)

        self.assertIn("Mamie XGMP", resultat["message"])
        self.assertIn("Contact d'une autre famille", resultat["message"])

    def test_non_regression_parent_deja_representant_rattache_famille_existante(self):
        """Le cas normal (parent déjà Représentant ailleurs) doit continuer à rattacher
        l'enfant à la famille existante, pas en créer une nouvelle - pas touché par le fix."""
        famille = Famille.objects.create(nom="FAMILLE EXISTANTE")
        xp = Individu.objects.create(nom="XP", prenom="Papa", civilite=1, ent_id="ENT-XP4")
        Rattachement.objects.create(individu=xp, famille=famille, categorie=1, titulaire=True)

        eleve_data = self._eleve_data("ENT-XE3E", parents=[{"id": "ENT-XP4"}])
        resultat = _importer_eleve_ent("ENT-XE3E", eleve_data=eleve_data, parents_cache={"ENT-XP4": {"id": "ENT-XP4", "lastName": "XP", "firstName": "Papa"}})

        self.assertEqual(resultat["statut"], "importe")
        self.assertEqual(resultat["type"], "famille_existante")
        self.assertEqual(resultat["famille_id"], famille.pk)


class TestAffichageParentContactSeulement(TestCase):
    """Le message d'aperçu de l'écran d'import (_effectuer_recherche) ne doit jamais dire
    "sera ajouté à la famille ." (nom vide) quand le seul parent déjà connu n'est que
    Contact ailleurs - même règle que TestImporterParentContactSeulement, côté affichage."""

    def _lancer_recherche(self, eleve_ent, parents_par_id):
        briefs = [{"id": eleve_ent["id"], "type": "Student"}]
        par_id = {eleve_ent["id"]: eleve_ent, **parents_par_id}

        request = RequestFactory().post("/", {"action": "rechercher", "first_name": "Test", "last_name": "Test"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()

        with patch("fiche_famille.views.famille_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_famille.views.famille_ent.search_by_name", return_value=briefs), \
             patch("fiche_famille.views.famille_ent.get_user", side_effect=lambda ent_id: par_id.get(ent_id)), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            ImporterFamilleEnt()._effectuer_recherche(request, "Test", "Test")

        return request.session.get("ent_resultats")

    def test_pas_de_message_casse_si_seul_parent_connu_est_contact(self):
        famille_a = Famille.objects.create(nom="FAMILLE A")
        xgmp = Individu.objects.create(nom="XGMP", prenom="Mamie", civilite=3, ent_id="ENT-XGMP5")
        Rattachement.objects.create(individu=xgmp, famille=famille_a, categorie=3, titulaire=False)

        eleve_ent = {"id": "ENT-XE5", "type": "Student", "firstName": "XE", "lastName": "TEST5", "parents": [{"id": "ENT-XGMP5"}]}
        resultats = self._lancer_recherche(eleve_ent, {"ENT-XGMP5": {"id": "ENT-XGMP5", "type": "Relative", "lastName": "XGMP", "firstName": "Mamie"}})

        self.assertFalse(resultats[0]["parents_existants"])
        self.assertIsNone(resultats[0]["parents_existants_msg"])

    def test_message_normal_si_parent_est_representant(self):
        """Non-régression : le message normal doit toujours s'afficher quand le parent
        déjà connu est bien Représentant quelque part."""
        famille = Famille.objects.create(nom="FAMILLE EXISTANTE")
        xp = Individu.objects.create(nom="XP", prenom="Papa", civilite=1, ent_id="ENT-XP5")
        Rattachement.objects.create(individu=xp, famille=famille, categorie=1, titulaire=True)

        eleve_ent = {"id": "ENT-XE6", "type": "Student", "firstName": "XE", "lastName": "TEST6", "parents": [{"id": "ENT-XP5"}]}
        resultats = self._lancer_recherche(eleve_ent, {"ENT-XP5": {"id": "ENT-XP5", "type": "Relative", "lastName": "XP", "firstName": "Papa"}})

        self.assertTrue(resultats[0]["parents_existants"])
        self.assertIn("FAMILLE EXISTANTE", resultats[0]["parents_existants_msg"])
        self.assertNotIn("famille .", resultats[0]["parents_existants_msg"])


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


class TestImporterEnMasseAffichageEtResume(TestCase):
    """Cas de ImporterEnMasseEnt jamais testés : connexion impossible, panne, masquage à
    l'affichage, élève déjà importé, aucune sélection, compteurs du résumé final, famille
    séparée comptée double, log unique dans l'historique."""

    def _get_contexte(self, eleves_bruts, headers_ret="ok", search_users_ret="defaut"):
        vue = ImporterEnMasseEnt()
        vue.request = RequestFactory().get("/")
        vue.request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        headers_value = None if headers_ret is None else {"Authorization": "Bearer test"}
        search_ret = eleves_bruts if search_users_ret == "defaut" else search_users_ret
        with patch("fiche_famille.views.famille_ent.get_headers", return_value=headers_value), \
             patch("fiche_famille.views.famille_ent.search_users", return_value=search_ret):
            return vue.get_context_data()

    def test_connexion_impossible(self):
        context = self._get_contexte([], headers_ret=None)
        self.assertTrue(context["erreur_connexion"])

    def test_panne_en_cours_dappel(self):
        """search_users() renvoie None (panne pendant l'appel) - distinct d'une vraie
        liste vide (l'ENT dit "aucun élève")."""
        context = self._get_contexte([], search_users_ret=None)
        self.assertTrue(context["erreur_connexion"])

    def test_ecole_inconnue_masquee_a_laffichage(self):
        eleve = {"id": "ENT-MASSEAFF-KO", "type": "Student", "firstName": "X", "lastName": "TEST",
                 "structures": [{"name": "Ecole Jamais A33", "uai": None, "id": "ENT-ECOLE-A33"}]}
        context = self._get_contexte([eleve])
        self.assertEqual(context["nb_masques_ecole_inconnue"], 1)
        self.assertEqual(context["eleves"], [])

    def test_eleve_deja_importe_est_marque(self):
        Ecole.objects.create(nom="Ecole A34", ent_id="ENT-ECOLE-A34")
        Individu.objects.create(nom="TEST34", prenom="Deja", civilite=4, ent_id="ENT-MASSEAFF-DEJA")
        eleve = {"id": "ENT-MASSEAFF-DEJA", "type": "Student", "firstName": "Deja", "lastName": "TEST34",
                 "structures": [{"name": "Ecole A34", "uai": None, "id": "ENT-ECOLE-A34"}]}
        context = self._get_contexte([eleve])
        self.assertTrue(context["eleves"][0]["deja_importe"])

    def test_aucun_eleve_selectionne(self):
        request = RequestFactory().post("/", {})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        response = ImporterEnMasseEnt().post(request)
        self.assertEqual(response.status_code, 302)

    def test_resume_et_log_pour_famille_separee(self):
        Ecole.objects.create(nom="Ecole A37", ent_id="ENT-ECOLE-A37")
        eleve_separe = {
            "id": "ENT-MASSE-SEP", "type": "Student", "firstName": "Sep", "lastName": "TEST37",
            "structures": [{"name": "Ecole A37", "uai": None, "id": "ENT-ECOLE-A37"}],
            "parents": [{"id": "ENT-P1-A37"}, {"id": "ENT-P2-A37"}],
        }
        par_id = {
            "ENT-MASSE-SEP": eleve_separe,
            "ENT-P1-A37": {"id": "ENT-P1-A37", "lastName": "P1", "firstName": "Papa", "address": "1 rue A", "zipCode": "45000"},
            "ENT-P2-A37": {"id": "ENT-P2-A37", "lastName": "P2", "firstName": "Maman", "address": "2 rue B", "zipCode": "45100"},
        }
        request = RequestFactory().post("/", {"eleves_ent_id": ["ENT-MASSE-SEP"]})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_famille.views.famille_ent.get_user", side_effect=lambda ent_id: par_id.get(ent_id)), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            ImporterEnMasseEnt().post(request)

        resume = request.session.get("ent_import_masse_resume")
        self.assertEqual(resume["nb_eleves_importes"], 1)
        self.assertEqual(resume["nb_nouvelles_familles"], 2, "une famille séparée doit compter comme 2 nouvelles familles")

        logs = Historique.objects.filter(titre="Import en masse depuis l'ENT")
        self.assertEqual(logs.count(), 1, "un seul log de lancement, pas une ligne par élève")


class TestImporterEnMasseRevalideEcoleAuClic(TestCase):
    """L'import en masse masque déjà les élèves d'école non reconnue à l'AFFICHAGE
    (get_context_data), mais ne revérifiait pas l'école au moment du clic "Importer"
    (post) - contrairement à l'import unitaire. Si la page reste ouverte et que l'école est
    supprimée entre-temps (Paramétrage > Écoles > Supprimer existe bien), un élève coché
    avant la suppression était importé quand même, sans scolarité, en silence."""

    @staticmethod
    def _eleve(ent_id, prenom, nom, ecole_nom, ecole_uai, ecole_ent_id):
        return {
            "id": ent_id, "type": "Student", "firstName": prenom, "lastName": nom,
            "structures": [{"name": ecole_nom, "uai": ecole_uai, "id": ecole_ent_id}],
            "parents": [],
        }

    def _importer(self, eleves_ent, ids_selectionnes):
        par_id = {e["id"]: e for e in eleves_ent}
        request = RequestFactory().post("/", {"eleves_ent_id": ids_selectionnes})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        with patch("fiche_famille.views.famille_ent.get_user", side_effect=lambda ent_id: par_id.get(ent_id)), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            ImporterEnMasseEnt().post(request)

    def test_ecole_supprimee_entre_temps_nest_pas_importe_silencieusement(self):
        """École jamais connue de Noethys au moment du clic (simule une suppression entre
        l'affichage et le clic, puisque post() ne relit jamais la liste affichée)."""
        eleve = self._eleve("ENT-MASSE-KO", "Retire", "TESTMASSE", "Ecole Retiree Entretemps", "UAI777", "ENT-ECOLE-777")

        self._importer([eleve], ["ENT-MASSE-KO"])

        self.assertFalse(
            Individu.objects.filter(ent_id="ENT-MASSE-KO").exists(),
            "L'élève a été importé alors que son école n'est plus reconnue - devrait être refusé au clic, comme l'import unitaire.",
        )

    def test_ecole_toujours_reconnue_importe_normalement(self):
        """Non-régression : le cas normal (école toujours là) doit continuer à fonctionner."""
        Ecole.objects.create(nom="École Toujours La", uai="UAI888", ent_id="ENT-ECOLE-888")
        eleve = self._eleve("ENT-MASSE-OK", "Reste", "TESTMASSE", "École Toujours La", "UAI888", "ENT-ECOLE-888")

        self._importer([eleve], ["ENT-MASSE-OK"])

        self.assertTrue(Individu.objects.filter(ent_id="ENT-MASSE-OK").exists())

    def test_cas_mixte_seul_lelevel_ecole_connue_est_importe(self):
        Ecole.objects.create(nom="École Connue Mix", uai="UAI999", ent_id="ENT-ECOLE-999")
        eleve_ok = self._eleve("ENT-MIX-OK", "Ok", "TESTMIX", "École Connue Mix", "UAI999", "ENT-ECOLE-999")
        eleve_ko = self._eleve("ENT-MIX-KO", "Ko", "TESTMIX", "Ecole Inconnue Mix", "UAI000", "ENT-ECOLE-000")

        self._importer([eleve_ok, eleve_ko], ["ENT-MIX-OK", "ENT-MIX-KO"])

        self.assertTrue(Individu.objects.filter(ent_id="ENT-MIX-OK").exists())
        self.assertFalse(Individu.objects.filter(ent_id="ENT-MIX-KO").exists())


class TestImporterFamilleEntFicheExistanteNonLiee(TestCase):
    """L'écran d'import unitaire ne détectait "déjà importé" que par ent_id - une fiche
    saisie à la main avant l'arrivée de l'ENT (ou jamais rapprochée) était invisible pour
    lui, et l'import créait un doublon silencieux. Un avertissement doit maintenant prévenir
    l'agent avant l'import, sans bloquer (l'agent peut avoir raison - ce n'est peut-être pas
    la même personne)."""

    def _lancer_recherche(self, eleve_ent):
        request = RequestFactory().post("/", {"action": "rechercher", "first_name": "Test", "last_name": "Test"})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()

        with patch("fiche_famille.views.famille_ent.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_famille.views.famille_ent.search_by_name", return_value=[{"id": eleve_ent["id"], "type": "Student"}]), \
             patch("fiche_famille.views.famille_ent.get_user", return_value=eleve_ent), \
             patch("fiche_famille.views.famille_ent.ThreadPoolExecutor", _SerialExecutor):
            ImporterFamilleEnt()._effectuer_recherche(request, "Test", "Test")

        return request.session.get("ent_resultats")

    @staticmethod
    def _eleve(ent_id, prenom, nom):
        return {"id": ent_id, "type": "Student", "firstName": prenom, "lastName": nom, "parents": []}

    def test_avertit_si_une_fiche_du_meme_nom_existe_sans_lien_ent(self):
        famille = Famille.objects.create(nom="HOMONYME")
        Individu.objects.create(nom="DUPONT", prenom="Alice", civilite=4)
        Rattachement.objects.create(
            individu=Individu.objects.get(nom="DUPONT", prenom="Alice"), famille=famille, categorie=2, titulaire=False,
        )

        resultats = self._lancer_recherche(self._eleve("ENT-NOUVEAU", "Alice", "DUPONT"))

        self.assertIsNotNone(resultats[0]["fiche_existante_msg"], "Aucun avertissement alors qu'une fiche non liée du même nom existe.")
        self.assertEqual(resultats[0]["fiche_existante_famille_id"], famille.pk)

    def test_pas_davertissement_si_aucune_fiche_existante(self):
        resultats = self._lancer_recherche(self._eleve("ENT-NOUVEAU2", "Bob", "MARTIN"))

        self.assertIsNone(resultats[0]["fiche_existante_msg"])

    def test_pas_davertissement_si_la_fiche_existante_est_deja_liee_a_lent(self):
        """Ce cas est déjà couvert par le message "déjà importé" - pas la peine de doubler
        l'avertissement."""
        famille = Famille.objects.create(nom="DEJALIE")
        individu = Individu.objects.create(nom="MARTIN", prenom="Chloe", civilite=4, ent_id="ENT-DEJA")
        Rattachement.objects.create(individu=individu, famille=famille, categorie=2, titulaire=False)

        resultats = self._lancer_recherche(self._eleve("ENT-DEJA", "Chloe", "MARTIN"))

        self.assertTrue(resultats[0]["deja_importe"])
        self.assertIsNone(resultats[0]["fiche_existante_msg"])

    def test_comparaison_insensible_aux_accents_et_a_la_casse(self):
        famille = Famille.objects.create(nom="ACCENTS")
        individu = Individu.objects.create(nom="LEGRAND", prenom="Chloé", civilite=4)
        Rattachement.objects.create(individu=individu, famille=famille, categorie=2, titulaire=False)

        # Côté ENT, sans accent et en majuscules - même personne
        resultats = self._lancer_recherche(self._eleve("ENT-NOUVEAU3", "CHLOE", "legrand"))

        self.assertIsNotNone(resultats[0]["fiche_existante_msg"], "L'accent/la casse ne devrait pas empêcher la détection.")

    def test_ne_declenche_pas_sur_un_parent_du_meme_nom(self):
        """La recherche ne doit porter que sur les ENFANTS (categorie=2) - un parent
        homonyme n'est pas le cas visé ici (et créerait de faux avertissements)."""
        famille = Famille.objects.create(nom="PARENT")
        individu = Individu.objects.create(nom="ROBERT", prenom="Julie", civilite=3)
        Rattachement.objects.create(individu=individu, famille=famille, categorie=1, titulaire=True)

        resultats = self._lancer_recherche(self._eleve("ENT-NOUVEAU4", "Julie", "ROBERT"))

        self.assertIsNone(resultats[0]["fiche_existante_msg"])


class TestAdressesDifferentesNormalisation(TestCase):
    """_adresses_differentes (détection de parents séparés à l'import) ne doit pas
    confondre une même adresse écrite différemment (accent, casse) avec une vraie
    adresse différente - mesuré sur les 696 élèves d'une recette ENT réelle : 0 faux
    positif actuellement, mais la comparaison ne normalisait pas du tout, contrairement
    aux noms et aux écoles ailleurs dans ce fichier. Précaution avant que ça n'arrive
    sur une vraie collectivité aux adresses accentuées."""

    def test_meme_adresse_avec_accent_different_nest_pas_differente(self):
        self.assertFalse(_adresses_differentes(
            {"address": "12 rue des Écoles", "zipCode": "45000"},
            {"address": "12 rue des Ecoles", "zipCode": "45000"},
        ))

    def test_meme_adresse_casse_differente_nest_pas_differente(self):
        self.assertFalse(_adresses_differentes(
            {"address": "12 RUE DES ECOLES", "zipCode": "45000"},
            {"address": "12 rue des ecoles", "zipCode": "45000"},
        ))

    def test_adresses_vraiment_differentes_restent_differentes(self):
        self.assertTrue(_adresses_differentes(
            {"address": "12 rue des Écoles", "zipCode": "45000"},
            {"address": "9 avenue du Parc", "zipCode": "45100"},
        ))

    def test_les_deux_adresses_vides_nest_pas_differente(self):
        """Non-régression : comportement déjà existant, ne doit pas changer."""
        self.assertFalse(_adresses_differentes({"address": "", "zipCode": ""}, {"address": "", "zipCode": ""}))


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


class TestSeparationPrestationFacturee(TestCase):
    """La règle de migration des prestations à la séparation manuelle (même principe que
    pour les inscriptions, voir TestMigrationInscriptionSeparation) ne doit jamais bouger
    une prestation déjà facturée - facturer.date/montant sont figés sur la facture émise,
    la déplacer romprait le lien entre la facture et la famille qui l'a réellement reçue."""

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

    def test_prestation_non_facturee_migre_si_titulaire_unique(self):
        famille = Famille.objects.create(nom="PREST NON FACT")
        parent = Individu.objects.create(nom="PREST", prenom="Papa", civilite=1)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        prestation = Prestation.objects.create(famille=famille, individu=parent, date=date(2026, 9, 1), label="Cantine")

        self._separer(famille, parent.pk)

        prestation.refresh_from_db()
        self.assertNotEqual(prestation.famille_id, famille.pk, "La prestation du parent qui part aurait dû migrer.")

    def test_prestation_facturee_ne_migre_jamais(self):
        famille = Famille.objects.create(nom="PREST FACT")
        parent = Individu.objects.create(nom="PREST2", prenom="Papa", civilite=1)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        facture = Facture.objects.create(famille=famille, numero=1, date_edition=date(2026, 9, 1), date_debut=date(2026, 9, 1), date_fin=date(2026, 9, 30))
        prestation = Prestation.objects.create(famille=famille, individu=parent, date=date(2026, 9, 1), label="Cantine", facture=facture)

        self._separer(famille, parent.pk)

        prestation.refresh_from_db()
        self.assertEqual(
            prestation.famille_id, famille.pk,
            "Une prestation déjà facturée ne doit jamais migrer, même pour le parent qui part lui-même.",
        )


class TestSeparationCasParticuliers(TestCase):
    """Cas limites de SeparerFamille : familles sans enfant, sans titulaire clair, et
    règles de copie/promotion des rattachements."""

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

    def test_zero_titulaire_rien_ne_migre_pour_les_enfants(self):
        famille = Famille.objects.create(nom="ZERO TITULAIRE")
        parent = Individu.objects.create(nom="ZT", prenom="Papa", civilite=1)
        autre_parent = Individu.objects.create(nom="ZT", prenom="Maman", civilite=3)
        enfant = Individu.objects.create(nom="ZT", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=False)
        Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=False)
        Rattachement.objects.create(individu=enfant, famille=famille, categorie=2, titulaire=False)
        prestation = Prestation.objects.create(famille=famille, individu=enfant, date=date(2026, 9, 1), label="Cantine")

        self._separer(famille, parent.pk)

        prestation.refresh_from_db()
        self.assertEqual(
            prestation.famille_id, famille.pk,
            "Aucun titulaire clair (0 titulaire) - la prestation de l'enfant devrait rester ambiguë.",
        )

    def test_tous_les_enfants_sont_copies_dans_la_nouvelle_famille(self):
        famille = Famille.objects.create(nom="COPIE ENFANTS")
        parent = Individu.objects.create(nom="CE", prenom="Papa", civilite=1)
        enfant1 = Individu.objects.create(nom="CE", prenom="Enfant1", civilite=4)
        enfant2 = Individu.objects.create(nom="CE", prenom="Enfant2", civilite=4)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant1, famille=famille, categorie=2, titulaire=False)
        Rattachement.objects.create(individu=enfant2, famille=famille, categorie=2, titulaire=False)

        self._separer(famille, parent.pk)

        nouvelle_famille = Famille.objects.exclude(pk=famille.pk).get(rattachement__individu=parent)
        for enfant in (enfant1, enfant2):
            self.assertTrue(
                Rattachement.objects.filter(individu=enfant, famille=nouvelle_famille, categorie=2).exists(),
                f"{enfant} aurait dû être copié dans la nouvelle famille (garde partagée par défaut).",
            )
            self.assertTrue(
                Rattachement.objects.filter(individu=enfant, famille=famille, categorie=2).exists(),
                f"{enfant} devrait rester rattaché à l'ancienne famille aussi.",
            )

    def test_promotion_automatique_titulaire_si_plus_aucun_ne_reste(self):
        famille = Famille.objects.create(nom="PROMOTION")
        parent = Individu.objects.create(nom="PR", prenom="Papa", civilite=1)
        autre_parent = Individu.objects.create(nom="PR", prenom="Maman", civilite=3)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        ratt_autre = Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=False)

        self._separer(famille, parent.pk)

        ratt_autre.refresh_from_db()
        self.assertTrue(
            ratt_autre.titulaire,
            "Le parent qui part était l'unique titulaire - l'autre représentant restant "
            "devrait être promu automatiquement, sinon plus personne n'est titulaire.",
        )

    def test_separation_famille_sans_enfant_ne_plante_pas(self):
        famille = Famille.objects.create(nom="SANS ENFANT")
        parent = Individu.objects.create(nom="SE", prenom="Papa", civilite=1)
        autre_parent = Individu.objects.create(nom="SE", prenom="Maman", civilite=3)
        Rattachement.objects.create(individu=parent, famille=famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=autre_parent, famille=famille, categorie=1, titulaire=False)

        self._separer(famille, parent.pk)

        nouvelle_famille = Famille.objects.exclude(pk=famille.pk).get(rattachement__individu=parent)
        self.assertTrue(Rattachement.objects.filter(individu=parent, famille=nouvelle_famille).exists())


class TestMigrationModelesParIndividuSeparation(TestCase):
    """_migrer_donnees_individu est une fonction générique appliquée aux 12 modèles de
    MODELES_A_MIGRER_PAR_INDIVIDU. On vérifie ici que chacun suit bien la règle (titulaire
    unique -> migre pour l'enfant partagé), pas seulement le principe sur un seul modèle."""

    def setUp(self):
        self.famille = Famille.objects.create(nom="MIGR MODELES")
        self.parent = Individu.objects.create(nom="MM", prenom="Papa", civilite=1)
        self.enfant = Individu.objects.create(nom="MM", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=self.parent, famille=self.famille, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=self.enfant, famille=self.famille, categorie=2, titulaire=False)

        assureur = Assureur.objects.create(nom="Assureur Test")
        type_cotisation = TypeCotisation.objects.create(nom="Type Test")
        unite_cotisation = UniteCotisation.objects.create(type_cotisation=type_cotisation, nom="Unité Test")
        question = QuestionnaireQuestion.objects.create(categorie="famille", ordre=1, label="Question", controle="texte")
        sondage = Sondage.objects.create(titre="Sondage Test")

        # Une instance de chaque modèle, rattachée à l'enfant partagé (categorie=2)
        self.instances = {
            Note: Note.objects.create(famille=self.famille, individu=self.enfant, date_parution=date(2026, 9, 1), texte="Note test"),
            Piece: Piece.objects.create(famille=self.famille, individu=self.enfant),
            Historique: Historique.objects.create(famille=self.famille, individu=self.enfant),
            Destinataire: Destinataire.objects.create(famille=self.famille, individu=self.enfant),
            DestinataireSMS: DestinataireSMS.objects.create(famille=self.famille, individu=self.enfant),
            QuestionnaireReponse: QuestionnaireReponse.objects.create(question=question, famille=self.famille, individu=self.enfant),
            PortailRenseignement: PortailRenseignement.objects.create(famille=self.famille, individu=self.enfant, categorie="individu_civilite", code="test"),
            ContactUrgence: ContactUrgence.objects.create(nom="Urg", prenom="Ence", lien="Voisin", individu=self.enfant, famille=self.famille),
            Assurance: Assurance.objects.create(individu=self.enfant, famille=self.famille, assureur=assureur, num_contrat="123", date_debut=date(2026, 9, 1)),
            SondageRepondant: SondageRepondant.objects.create(sondage=sondage, famille=self.famille, individu=self.enfant),
            Cotisation: Cotisation.objects.create(famille=self.famille, individu=self.enfant, type_cotisation=type_cotisation, unite_cotisation=unite_cotisation, date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31)),
            Mandat: Mandat.objects.create(famille=self.famille, rum="RUM-TEST", date=date(2026, 9, 1), individu=self.enfant, iban="FR7630006000011234567890189", bic="AGRIFRPP"),
        }

    def _separer(self):
        request = RequestFactory().post("/", {"id_parent": self.parent.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = SeparerFamille()
        vue.request = request
        vue.kwargs = {"idfamille": self.famille.pk}
        vue.post(request)

    def test_chaque_modele_migre_pour_enfant_partage_si_titulaire_unique(self):
        self._separer()

        nouvelle_famille = Famille.objects.exclude(pk=self.famille.pk).get(rattachement__individu=self.parent)

        for model, instance in self.instances.items():
            instance.refresh_from_db()
            self.assertEqual(
                instance.famille_id, nouvelle_famille.pk,
                f"{model.__name__} n'a pas migré pour l'enfant partagé alors que le parent "
                f"qui part est l'unique titulaire du dossier.",
            )


class TestFusionMigrationGenerique(TestCase):
    """FusionnerFamilles migre TOUT ce qui a une FK vers Famille, via introspection de
    Famille._meta.related_objects - pas seulement les modèles de la liste séparation.
    On vérifie ça sur des modèles représentatifs (financier, individuel)."""

    def test_migration_payeur_et_facture(self):
        famille_cible = Famille.objects.create(nom="FUS GEN CIBLE")
        famille_source = Famille.objects.create(nom="FUS GEN SOURCE")
        payeur = Payeur.objects.create(famille=famille_source, nom="Payeur Source")
        facture = Facture.objects.create(famille=famille_source, numero=1, date_edition=date(2026, 9, 1), date_debut=date(2026, 9, 1), date_fin=date(2026, 9, 30))

        _fusionner(famille_cible, famille_source)

        payeur.refresh_from_db()
        facture.refresh_from_db()
        self.assertEqual(payeur.famille_id, famille_cible.pk)
        self.assertEqual(facture.famille_id, famille_cible.pk)

    def test_migration_note_liee_a_individu(self):
        famille_cible = Famille.objects.create(nom="FUS NOTE CIBLE")
        famille_source = Famille.objects.create(nom="FUS NOTE SOURCE")
        individu = Individu.objects.create(nom="FUSNOTE", prenom="Enfant", civilite=4)
        note = Note.objects.create(famille=famille_source, individu=individu, date_parution=date(2026, 9, 1), texte="Note")

        _fusionner(famille_cible, famille_source)

        note.refresh_from_db()
        self.assertEqual(note.famille_id, famille_cible.pk)


class TestFusionRattachement(TestCase):
    """La fusion gère les Rattachement à part (avant la boucle générique) : un enfant
    partagé présent dans les 2 familles ne doit pas se retrouver en double après fusion."""

    def test_rattachement_duplique_garde_la_version_cible(self):
        famille_cible = Famille.objects.create(nom="FUS RATT CIBLE")
        famille_source = Famille.objects.create(nom="FUS RATT SOURCE")
        enfant = Individu.objects.create(nom="FUSRATT", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=enfant, famille=famille_cible, categorie=2, titulaire=False, certification_date=datetime(2026, 1, 1))
        ratt_source = Rattachement.objects.create(individu=enfant, famille=famille_source, categorie=2, titulaire=False, certification_date=datetime(2026, 6, 1))
        id_ratt_source = ratt_source.pk

        _fusionner(famille_cible, famille_source)

        self.assertFalse(
            Rattachement.objects.filter(pk=id_ratt_source).exists(),
            "Le rattachement en double, côté source, aurait dû être supprimé.",
        )
        ratt_final = Rattachement.objects.get(individu=enfant, famille=famille_cible)
        self.assertEqual(
            ratt_final.certification_date, datetime(2026, 1, 1),
            "La fusion doit garder la version de la famille cible en cas de doublon, "
            "pas écraser avec les infos de la source.",
        )

    def test_rattachement_non_duplique_migre_normalement(self):
        famille_cible = Famille.objects.create(nom="FUS RATT2 CIBLE")
        famille_source = Famille.objects.create(nom="FUS RATT2 SOURCE")
        parent = Individu.objects.create(nom="FUSRATT2", prenom="Parent", civilite=1)
        ratt = Rattachement.objects.create(individu=parent, famille=famille_source, categorie=1, titulaire=True)

        _fusionner(famille_cible, famille_source)

        ratt.refresh_from_db()
        self.assertEqual(ratt.famille_id, famille_cible.pk)


class TestFusionCasParticuliers(TestCase):
    """Cas limites de FusionnerFamilles : réinitialisation du mode_separation, requête
    incomplète, et non-régression sur un doublon d'inscription pré-existant."""

    def test_mode_separation_reinitialise_sur_la_cible(self):
        famille_cible = Famille.objects.create(nom="FUS MODE CIBLE", mode_separation="force")
        famille_source = Famille.objects.create(nom="FUS MODE SOURCE")

        _fusionner(famille_cible, famille_source)

        famille_cible.refresh_from_db()
        self.assertIsNone(famille_cible.mode_separation)

    def test_idfamille_source_manquant_ne_plante_pas(self):
        famille_cible = Famille.objects.create(nom="FUS ERR CIBLE")

        request = RequestFactory().post("/", {})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")

        vue = FusionnerFamilles()
        vue.request = request
        vue.kwargs = {"idfamille": famille_cible.pk}
        response = vue.post(request)

        self.assertEqual(response.status_code, 302, "Doit rediriger proprement, pas planter, si aucune famille source n'est sélectionnée.")
        self.assertTrue(Famille.objects.filter(pk=famille_cible.pk).exists())

    def test_doublon_inscription_preexistant_ne_fait_pas_planter_la_fusion(self):
        """Non-régression : le doublon lui-même est empêché à la création (voir
        check_inscriptions_existantes, fiche_individu), mais si un doublon existe déjà
        (données anciennes, ou activité inscriptions_multiples=True), la fusion ne doit
        pas planter - elle bascule les deux inscriptions dans la même famille, comme
        n'importe quelle autre donnée."""
        structure = Structure.objects.create(nom="Structure Multi")
        activite = Activite.objects.create(nom="Atelier", abrege="ATEL", structure=structure, inscriptions_multiples=True)
        groupe = Groupe.objects.create(activite=activite, nom="Groupe", ordre=1)
        categorie_tarif = CategorieTarif.objects.create(activite=activite, nom="Standard")

        famille_cible = Famille.objects.create(nom="FUS DOUBLON CIBLE")
        famille_source = Famille.objects.create(nom="FUS DOUBLON SOURCE")
        enfant = Individu.objects.create(nom="FUSDOUBLON", prenom="Enfant", civilite=4)
        insc_cible = Inscription.objects.create(individu=enfant, famille=famille_cible, activite=activite, groupe=groupe, categorie_tarif=categorie_tarif, date_debut=date(2026, 9, 1))
        insc_source = Inscription.objects.create(individu=enfant, famille=famille_source, activite=activite, groupe=groupe, categorie_tarif=categorie_tarif, date_debut=date(2026, 9, 1))

        _fusionner(famille_cible, famille_source)

        insc_cible.refresh_from_db()
        insc_source.refresh_from_db()
        self.assertEqual(insc_cible.famille_id, famille_cible.pk)
        self.assertEqual(insc_source.famille_id, famille_cible.pk)


class TestSeparerPuisRefusionner(TestCase):
    """Cas combiné : les deux parents se séparent puis se réconcilient. Rien ne doit être
    perdu ni dupliqué à l'arrivée, même si des données ont migré entre-temps."""

    def test_aller_retour_sans_perte_ni_duplication(self):
        famille_origine = Famille.objects.create(nom="AR ORIGINE")
        parent_qui_reste = Individu.objects.create(nom="AR", prenom="Maman", civilite=3)
        parent_qui_part = Individu.objects.create(nom="AR", prenom="Papa", civilite=1)
        enfant = Individu.objects.create(nom="AR", prenom="Enfant", civilite=4)
        Rattachement.objects.create(individu=parent_qui_reste, famille=famille_origine, categorie=1, titulaire=False)
        Rattachement.objects.create(individu=parent_qui_part, famille=famille_origine, categorie=1, titulaire=True)
        Rattachement.objects.create(individu=enfant, famille=famille_origine, categorie=2, titulaire=False)
        prestation = Prestation.objects.create(famille=famille_origine, individu=enfant, date=date(2026, 9, 1), label="Cantine")

        # Étape 1 : séparation - parent_qui_part est l'unique titulaire, donc la
        # prestation de l'enfant partagé migre avec lui vers la nouvelle famille.
        request = RequestFactory().post("/", {"id_parent": parent_qui_part.pk})
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        vue = SeparerFamille()
        vue.request = request
        vue.kwargs = {"idfamille": famille_origine.pk}
        vue.post(request)

        nouvelle_famille = Famille.objects.exclude(pk=famille_origine.pk).get(rattachement__individu=parent_qui_part)
        prestation.refresh_from_db()
        self.assertEqual(prestation.famille_id, nouvelle_famille.pk, "Pré-requis du test : la prestation doit avoir migré à la séparation.")

        # Étape 2 : les parents se réconcilient - on fusionne la nouvelle famille
        # (parent_qui_part) dans la famille d'origine.
        _fusionner(famille_origine, nouvelle_famille)

        prestation.refresh_from_db()
        self.assertEqual(prestation.famille_id, famille_origine.pk, "La prestation doit revenir dans la famille d'origine après la fusion.")

        self.assertEqual(
            Rattachement.objects.filter(individu=enfant, famille=famille_origine).count(), 1,
            "L'enfant ne doit pas se retrouver rattaché en double à la famille d'origine après l'aller-retour.",
        )
        self.assertTrue(
            Rattachement.objects.filter(individu=parent_qui_part, famille=famille_origine, categorie=1).exists(),
            "Le parent qui était parti devrait être de retour, rattaché à la famille d'origine.",
        )


class TestListeSynchroIntrouvable(TestCase):
    """Synchro en masse : distingue une vraie panne d'une confirmation ENT (compte
    disparu), et ne dit plus "Aucun champ sélectionné" quand l'agent avait bien coché des
    champs qui ont simplement échoué (avant : échec totalement silencieux, message final
    carrément faux dans ce cas)."""

    def _get_context(self, side_effect):
        vue = ListeSynchro()
        vue.request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(vue.request)
        vue.request.session.save()
        vue.request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        with patch("fiche_famille.views.famille_ent_synchro.get_headers", return_value={"Authorization": "Bearer test"}), \
             patch("fiche_famille.views.famille_ent_synchro.get_user_ou_introuvable", side_effect=side_effect):
            return vue.get_context_data()

    def test_affichage_distingue_introuvable_de_panne(self):
        individu_parti = Individu.objects.create(nom="PARTI", prenom="Eleve", civilite=4, ent_id="ENT-PARTI-MASSE")
        individu_panne = Individu.objects.create(nom="PANNE", prenom="Eleve", civilite=4, ent_id="ENT-PANNE-MASSE")

        def fake(ent_id):
            return (None, True) if ent_id == "ENT-PARTI-MASSE" else (None, False)

        context = self._get_context(fake)

        lignes = {l["individu"].pk: l for l in context["lignes"]}
        self.assertTrue(lignes[individu_parti.pk]["introuvable"])
        self.assertFalse(lignes[individu_panne.pk]["introuvable"])
        self.assertTrue(lignes[individu_panne.pk]["erreur"])

    def _post(self, individus_champs, side_effect):
        data = {f"champs_{individu.pk}": champs for individu, champs in individus_champs.items()}
        request = RequestFactory().post("/", data)
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = Utilisateur.objects.create_user(username=f"agent_test_{uuid.uuid4().hex[:12]}")
        with patch("fiche_famille.views.famille_ent_synchro.get_user_ou_introuvable", side_effect=side_effect):
            ListeSynchro().post(request)
        from django.contrib.messages import get_messages
        return [(m.level_tag, str(m)) for m in get_messages(request)]

    def test_echec_ne_dit_plus_aucun_champ_selectionne(self):
        individu = Individu.objects.create(nom="ECHECMASSE", prenom="Eleve", civilite=4, ent_id="ENT-ECHEC-MASSE")

        msgs = self._post({individu: ["nom"]}, side_effect=lambda ent_id: (None, True))

        self.assertFalse(
            any("Aucun champ sélectionné" in m for _, m in msgs),
            "Ne devrait plus dire ça - l'agent avait bien coché un champ, il a juste échoué.",
        )
        self.assertTrue(any("non synchronisé" in m and "n'existe plus dans l'ENT" in m for _, m in msgs))

    def test_aucun_champ_coche_dit_bien_aucun_champ_selectionne(self):
        """Non-régression : le vrai cas "rien coché du tout" garde son message."""
        msgs = self._post({}, side_effect=lambda ent_id: (None, False))

        self.assertTrue(any("Aucun champ sélectionné" in m for _, m in msgs))

    def test_succes_normal_fonctionne_toujours(self):
        individu = Individu.objects.create(nom="OKMASSE", prenom="Eleve", civilite=4, ent_id="ENT-OK-MASSE", mail="ancien@test.fr")

        msgs = self._post({individu: ["mail"]}, side_effect=lambda ent_id: ({"email": "nouveau@test.fr"}, False))

        individu.refresh_from_db()
        self.assertEqual(individu.mail, "nouveau@test.fr")
        self.assertTrue(any("synchronisé" in m for _, m in msgs))
