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
from fiche_famille.views.famille_ent import FusionnerFamilles, ImporterFamilleEnt, PreLiaisonEnt, SeparerFamille, _importer_eleve_ent
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
