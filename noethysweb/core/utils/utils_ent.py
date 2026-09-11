import logging
import requests # pour faire les appels API vers l'ENT
from django.conf import settings
from django.core.cache import cache # pour stocker la data en memoire rapide

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = "ent_access_token" # le nom de la clé du token dans le cache


# fonctionne interne, recupère l'organisateur depuis le cache ou la BD
def _get_organisateur():
    organisateur = cache.get("organisateur")
    if not organisateur:
        from core.models import Organisateur
        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur:
            cache.set("organisateur", organisateur)
    return organisateur


def ent_est_actif():
    """Vrai si l'intégration ENT est activée dans Paramétrage - à revérifier au début de
    chaque écran ENT, pas seulement en cachant ses boutons (une URL tapée à la main doit
    être bloquée pareil)."""
    organisateur = _get_organisateur()
    return bool(organisateur and organisateur.ent_active)


def get_token():
    """Récupère un token OAuth2 depuis l'ENT. Mis en cache 50 minutes (token valable 1h)."""
    token = cache.get(TOKEN_CACHE_KEY)
    if token:
        return token

    organisateur = _get_organisateur()
    if not organisateur or not organisateur.ent_active:
        return None
    if not all([settings.ENT_URL, settings.ENT_CLIENT_ID, settings.ENT_CLIENT_SECRET,
                organisateur.ent_username, organisateur.ent_password]):
        logger.warning("ENT : credentials incomplets dans le paramétrage.")
        return None

    try:
        r = requests.post(
            f"{settings.ENT_URL.rstrip('/')}/auth/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": settings.ENT_CLIENT_ID,
                "client_secret": settings.ENT_CLIENT_SECRET,
                "username": organisateur.ent_username,
                "password": organisateur.ent_password,
                "scope": "directory",
            },
            timeout=10,
        )
        r.raise_for_status() # raise une exception si le code HTTP n'est pas 200
        token = r.json().get("access_token") # recupère le token dans la réponse JSON (le token dans access_token)
        if token:
            cache.set(TOKEN_CACHE_KEY, token, timeout=3000)  # 50 minutes
        return token
    except Exception as e:
        logger.error("ENT : échec de l'authentification OAuth2 : %s", e)
        return None


def get_headers():
    """Retourne les headers Authorization pour les appels API ENT."""
    token = get_token()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _get_base_url():
    if not settings.ENT_URL:
        return None
    return settings.ENT_URL.rstrip("/")


class IntrouvableEnt(Exception):
    """Levée par _api_get (seulement si lever_si_introuvable=True) quand l'ENT confirme,
    après une éventuelle relance pour token expiré, que la ressource demandée n'existe pas
    (404) - à distinguer d'une vraie panne réseau, qui renvoie toujours None."""
    pass


def _api_get(url, params=None, retry=True, lever_si_introuvable=False):
    """Appel GET avec retry automatique si le token est expiré."""
    headers = get_headers()
    if not headers:
        return None
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code in (401, 404) and retry:
            # Token peut-être expiré — on le vide et on réessaie une fois
            cache.delete(TOKEN_CACHE_KEY)
            logger.warning("ENT : token expiré, retry...")
            return _api_get(url, params=params, retry=False, lever_si_introuvable=lever_si_introuvable)
        if r.status_code == 404 and lever_si_introuvable:
            raise IntrouvableEnt(url)
        r.raise_for_status()
        return r.json()
    except IntrouvableEnt:
        raise
    except Exception as e:
        logger.error("ENT : échec GET %s : %s", url, e)
        return None


def search_users(profile=None, structure_id=None):
    """
    GET /directory/user/admin/list
    Retourne tous les utilisateurs d'un profil, filtrés optionnellement par école.
    profile : 'Student', 'Relative', 'Teacher', 'Personnel'
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    params = {}
    if profile:
        params["profile"] = profile
    if structure_id:
        params["structureId"] = structure_id

    # Voir search_by_name : on laisse passer le None de _api_get, sinon une panne devient
    # indiscernable d'un ENT qui n'a réellement aucun élève.
    return _api_get(f"{base_url}/directory/user/admin/list", params=params)


def search_by_name(last_name, first_name):
    """
    Recherche par prénom ET nom, tous profils confondus (Student ET Relative).
    Retourne None si la connexion échoue, liste vide si aucun résultat.
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    params = {"firstName": first_name, "lastName": last_name}
    # _api_get ne renvoie None qu'en cas d'échec technique (credentials absents, timeout,
    # erreur HTTP après retry) - une recherche sans résultat renvoie une liste vide. On laisse
    # donc passer ce None tel quel : l'appelant doit pouvoir distinguer "l'ENT n'a pas répondu"
    # de "l'ENT a répondu qu'il ne connaît personne". Sans ça, une panne passagère est annoncée
    # à l'agent comme une absence de fiche - et en traitement de masse, chaque personne touchée
    # par l'incident reçoit une raison fausse.
    return _api_get(f"{base_url}/directory/user/admin/list", params=params)




def get_user(ent_id):
    """
    GET /directory/user/:userid
    Retourne les données complètes d'un utilisateur (adresse, email, enfants, parents...).
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    return _api_get(f"{base_url}/directory/user/{ent_id}")


def get_user_ou_introuvable(ent_id):
    """
    Comme get_user, mais distingue une vraie panne d'une confirmation de l'ENT que ce
    compte n'existe plus (élève parti, compte supprimé) - get_user seul renvoie None dans
    les deux cas, ce qui fait dire à tort "vérifiez la connexion" à un agent qui synchronise
    une personne qui a simplement quitté l'établissement. Réservée aux écrans de
    synchronisation, où cette distinction change concrètement le message affiché - ne
    remplace pas get_user() pour ses autres usages (import, corroboration...).
    Retourne (data, introuvable) - un seul des deux est "utile" à la fois.
    """
    base_url = _get_base_url()
    if not base_url:
        return None, False
    try:
        return _api_get(f"{base_url}/directory/user/{ent_id}", lever_si_introuvable=True), False
    except IntrouvableEnt:
        return None, True


def get_school(school_id):
    """
    GET /directory/school/:schoolid
    Retourne les infos d'un établissement (nom, UAI, adresse...). Accepte soit l'identifiant
    interne de l'établissement, soit son code UAI, indifféremment.
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    return _api_get(f"{base_url}/directory/school/{school_id}")


def get_classes(structure_id):
    """
    GET /directory/class/admin/list
    Retourne les classes d'un établissement.
    """
    base_url = _get_base_url()
    if not base_url:
        return []

    result = _api_get(f"{base_url}/directory/class/admin/list", params={"structureId": structure_id})
    return result if result is not None else []
