# -*- coding: utf-8 -*-
"""
Couche métier du SSO ENT : une fois l'identité du parent confirmée par le fournisseur
d'identité (peu importe le protocole - OIDC, CAS ou autre), ce module retrouve le compte
portail correspondant. Ne contient aucune logique de protocole - l'appelant (backend OIDC...)
doit avoir déjà validé l'identité avant d'appeler ces fonctions.
"""

from core.models import Individu, Famille, PortailParametre
from core.constants import TYPE_COMPTE_FAMILLE
from core.utils import utils_historique


def resoudre_utilisateur_ent(ent_id):
    """
    Retrouve le compte portail lié à cet ent_id, sans rien connecter ni tracer - pure lecture.
    Renvoie (utilisateur, erreur) - un seul des deux est renseigné.
    Reproduit les mêmes contrôles que la connexion par mot de passe (FormLoginFamille) pour
    qu'un compte refusé par un agent (désactivé, mauvaise catégorie) le soit aussi via le SSO.

    Selon le paramètre "type_compte" (Paramétrage > Portail), le compte de connexion est
    porté soit par la Famille (cas normal : un parent se connecte pour toute la famille),
    soit directement par l'Individu (mode "compte individuel") - ce n'est jamais l'Individu
    dans le premier cas, d'où la recherche par Rattachement plutôt que Individu.utilisateur.
    """
    individu = Individu.objects.filter(ent_id=ent_id).first()
    if not individu:
        return None, "Aucun compte ne correspond à cette identité ENT."

    parametre_type_compte = PortailParametre.objects.filter(code="type_compte").first()
    type_compte = parametre_type_compte.valeur if parametre_type_compte else TYPE_COMPTE_FAMILLE

    if type_compte == "individu":
        utilisateur = individu.utilisateur
    else:
        familles_avec_compte = Famille.objects.filter(
            rattachement__individu=individu, rattachement__categorie=1, utilisateur__isnull=False
        ).distinct()
        if familles_avec_compte.count() > 1:
            return None, "Plusieurs familles avec un compte portail correspondent à cette personne - liaison ambiguë, à vérifier à la main."
        utilisateur = familles_avec_compte.first().utilisateur if familles_avec_compte.exists() else None

    if not utilisateur:
        return None, "Cette personne est connue mais n'a pas de compte portail."
    if not utilisateur.is_active:
        return None, "Ce compte a été désactivé."
    if utilisateur.categorie != type_compte:
        return None, "Ce type de compte n'est pas autorisé à se connecter au portail."

    return utilisateur, None


def tracer_connexion_sso(utilisateur):
    """Trace une connexion réussie via SSO ENT dans l'Historique - commun à tous les protocoles."""
    famille_pk = utilisateur.famille.pk if utilisateur.categorie == "famille" else None
    utils_historique.Ajouter(titre="Connexion au portail (SSO ENT)", utilisateur=utilisateur, famille=famille_pk, portail=True)
