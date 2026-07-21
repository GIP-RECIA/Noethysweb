import logging
import requests # pour faire les appels API vers l'ENT
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


def get_token():
    """Récupère un token OAuth2 depuis l'ENT. Mis en cache 50 minutes (token valable 1h)."""
    token = cache.get(TOKEN_CACHE_KEY)
    if token:
        return token

    organisateur = _get_organisateur()
    if not organisateur or not organisateur.ent_active:
        return None
    if not all([organisateur.ent_url, organisateur.ent_client_id,
                organisateur.ent_client_secret, organisateur.ent_username, organisateur.ent_password]):
        logger.warning("ENT : credentials incomplets dans le paramétrage.")
        return None

    try:
        r = requests.post(
            f"{organisateur.ent_url.rstrip('/')}/auth/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": organisateur.ent_client_id,
                "client_secret": organisateur.ent_client_secret,
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
    organisateur = _get_organisateur()
    if not organisateur or not organisateur.ent_url:
        return None
    return organisateur.ent_url.rstrip("/")


def _api_get(url, params=None, retry=True):
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
            return _api_get(url, params=params, retry=False)
        r.raise_for_status()
        return r.json()
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
        return []

    params = {}
    if profile:
        params["profile"] = profile
    if structure_id:
        params["structureId"] = structure_id

    result = _api_get(f"{base_url}/directory/user/admin/list", params=params)
    return result if result is not None else []


def search_students_by_name(last_name, first_name, structure_id=None):
    """
    Recherche des élèves par prénom ET nom (obligatoires tous les deux).
    L'API exige les deux ensemble — un seul retourne 404.
    """
    base_url = _get_base_url()
    if not base_url:
        return []

    params = {"firstName": first_name, "lastName": last_name}
    if structure_id:
        params["structureId"] = structure_id

    result = _api_get(f"{base_url}/directory/user/admin/list", params=params)
    return result if result is not None else []


def search_by_name(last_name, first_name):
    """
    Recherche par prénom ET nom, tous profils confondus (Student ET Relative).
    Retourne None si la connexion échoue, liste vide si aucun résultat.
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    params = {"firstName": first_name, "lastName": last_name}
    result = _api_get(f"{base_url}/directory/user/admin/list", params=params)
    return result if result is not None else []




def get_user(ent_id):
    """
    GET /directory/user/:userid
    Retourne les données complètes d'un utilisateur (adresse, email, enfants, parents...).
    """
    base_url = _get_base_url()
    if not base_url:
        return None

    return _api_get(f"{base_url}/directory/user/{ent_id}")


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
