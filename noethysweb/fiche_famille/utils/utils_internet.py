# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, random, datetime

logger = logging.getLogger(__name__)
from django.conf import settings
from core.models import Famille, Utilisateur , Individu
from fiche_famille.utils import utils_internet


def CreationIdentifiantGeneric(type_compte="F", id_objet=None, IDutilisateur=None, nbreCaract=8):
    """ Création d'un identifiant aléatoire """
    numTmp = ""
    for x in range(0, nbreCaract-4):
        numTmp += random.choice("123456789")
    identifiant = numTmp + "0" * 5
    if id_objet:
        identifiant = u"%s%d" % (type_compte, int(identifiant) + id_objet)
    if IDutilisateur:
        identifiant = u"U%d" % (int(identifiant) + IDutilisateur)
    return identifiant


def CreationIdentifiant(IDfamille=None, IDutilisateur=None, nbreCaract=8):
    """ Création d'un identifiant aléatoire pour une famille """
    return CreationIdentifiantGeneric(type_compte="F", id_objet=IDfamille, IDutilisateur=IDutilisateur, nbreCaract=nbreCaract)


def CreationIdentifiantIndividu(IDindividu=None, IDutilisateur=None, nbreCaract=8):
    """ Création d'un identifiant aléatoire pour un individu """
    return CreationIdentifiantGeneric(type_compte="I", id_objet=IDindividu, IDutilisateur=IDutilisateur, nbreCaract=nbreCaract)


def CreationMDP(nbreCaract=10):
    """ Création d'un mot de passe aléatoire """
    mdp = "".join([random.choice("bcdfghjkmnprstvwxzBCDFGHJKLMNPRSTVWXZ123456789") for x in range(0, nbreCaract)])
    date_expiration = CreationDateExpirationMDP()
    return mdp, date_expiration


def CreationDateExpirationMDP():
    """ Génération de la date d'expiration d'un mdp """
    return datetime.datetime.now() + datetime.timedelta(seconds=settings.DUREE_VALIDITE_MDP) if settings.DUREE_VALIDITE_MDP else None


def ReinitTousMdp():
    """ Réinitialise tous les mots de passe familles et individus """
    def _reinit_mdp_objet(objet, categorie_objet):
        """Fonction interne pour réinitialiser le mot de passe d'un objet (famille ou individu)"""
        internet_mdp, date_expiration_mdp = utils_internet.CreationMDP()
        objet.internet_mdp = internet_mdp

        if not objet.utilisateur:
            utilisateur = Utilisateur(
                username=objet.internet_identifiant,
                categorie=categorie_objet,
                force_reset_password=True,
                date_expiration_mdp=date_expiration_mdp
            )
            utilisateur.save()
            utilisateur.set_password(internet_mdp)
            utilisateur.save()
            objet.utilisateur = utilisateur
        else:
            objet.utilisateur.set_password(internet_mdp)
            objet.utilisateur.force_reset_password = True
            objet.utilisateur.date_expiration_mdp = date_expiration_mdp
            objet.utilisateur.save()

        objet.save()

    # Réinitialisation pour les familles
    if Famille.objects.select_related("utilisateur"):
        for famille in Famille.objects.select_related("utilisateur").all():
            _reinit_mdp_objet(famille, "famille")

    # Réinitialisation pour les individus
    if Individu.objects.select_related("utilisateur"):
        for individu in Individu.objects.select_related("utilisateur").all():
            _reinit_mdp_objet(individu, "individu")


def Purge_mdp_expires():
    """ Efface tous les mdp expirés """
    def _purge_mdp_utilisateur(utilisateur, objet):
        """Fonction interne pour purger le mot de passe d'un utilisateur"""
        if getattr(utilisateur, objet, None):
            logger.debug("Purge du mot de passe expiré de %s." % utilisateur.username)
            utilisateur.set_password(None)
            utilisateur.save()
            getattr(utilisateur, objet).internet_mdp = None
            getattr(utilisateur, objet).save()

    # Purge pour les familles
    if Utilisateur.objects.select_related("famille"):
        utilisateurs = Utilisateur.objects.select_related("famille").filter(
            categorie="famille", 
            date_expiration_mdp__lte=datetime.datetime.now() - datetime.timedelta(days=3)
        )
        for utilisateur in utilisateurs:
            _purge_mdp_utilisateur(utilisateur, "famille")

    # Purge pour les individus
    if Utilisateur.objects.select_related("individu"):
        utilisateurs = Utilisateur.objects.select_related("individu").filter(
            categorie="individu", 
            date_expiration_mdp__lte=datetime.datetime.now() - datetime.timedelta(days=3)
        )
        for utilisateur in utilisateurs:
            _purge_mdp_utilisateur(utilisateur, "individu")


def Fix_dates_expiration_mdp():
    """ Applique une date d'expiration aux mots de passe existants """
    def _appliquer_date_expiration(objet):
        """Fonction interne pour appliquer une date d'expiration"""
        if "*****" not in objet.internet_mdp:
            logger.debug(
                "Application d'une date d'expiration MDP pour %s" % 
                objet.utilisateur.username
            )
            objet.utilisateur.date_expiration_mdp = CreationDateExpirationMDP()
            objet.utilisateur.save()

    # Application pour les familles
    if Famille.objects.select_related("utilisateur"):
        familles = Famille.objects.select_related("utilisateur").filter(
            utilisateur__date_expiration_mdp__isnull=True
        )
        for famille in familles:
            _appliquer_date_expiration(famille)

    # Application pour les individus
    if Individu.objects.select_related("utilisateur"):
        individus = Individu.objects.select_related("utilisateur").filter(
            utilisateur__date_expiration_mdp__isnull=True
        )
        for individu in individus:
            _appliquer_date_expiration(individu)
