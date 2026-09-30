# -*- coding: utf-8 -*-
"""
Backend OIDC pour le SSO parent (PrimOT -> CoCliCo). Branche mozilla-django-oidc sur la couche
métier existante (utils_ent_sso) - ne crée jamais de compte : seul un compte déjà lié via ent_id
peut se connecter. mozilla-django-oidc appelle lui-même login() après authenticate(), donc ce
backend n'a qu'à résoudre l'identité et renvoyer le bon utilisateur (ou None pour refuser).
"""

import logging

from django.conf import settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from portail.utils.utils_ent_sso import resoudre_utilisateur_ent, tracer_connexion_sso

logger = logging.getLogger(__name__)


class OIDCBackendEnt(OIDCAuthenticationBackend):

    def verify_claims(self, claims):
        # Le contrôle par défaut exige "email" dans les claims (scope "openid email") - on
        # exige plutôt la présence de l'identifiant ENT, seule donnée dont on a besoin.
        claim_ent_id = getattr(settings, "OIDC_ENT_ID_CLAIM", "sub")
        return bool(claims.get(claim_ent_id))

    def get_or_create_user(self, access_token, id_token, payload):
        claims = self.get_userinfo(access_token, id_token, payload)
        claim_ent_id = getattr(settings, "OIDC_ENT_ID_CLAIM", "sub")
        ent_id = claims.get(claim_ent_id)
        if not ent_id:
            logger.warning("SSO ENT : claim '%s' absente de la réponse OIDC.", claim_ent_id)
            return None

        utilisateur, erreur = resoudre_utilisateur_ent(ent_id)
        if erreur:
            logger.warning("SSO ENT : connexion refusée pour ent_id=%s (%s)", ent_id, erreur)
            return None

        tracer_connexion_sso(utilisateur)
        return utilisateur
