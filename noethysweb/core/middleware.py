#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.conf import settings
from django.http import HttpResponseRedirect

class URLPrefixMiddleware:
    """Middleware pour gérer le préfixe URL_ROOT"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        
        if not settings.URL_ROOT:
            # Pas de préfixe, comportement normal
            return self.get_response(request)
        
        # Normaliser URL_ROOT
        url_prefix = settings.URL_ROOT.strip('/')
        if not url_prefix:
            return self.get_response(request)
        
        # Si l'URL commence déjà par le préfixe, on retire le préfixe pour le traitement interne
        # Exemple: /app1/administrateur/ -> /administrateur/
        if request.path_info.startswith(f'/{url_prefix}/'):
            # Sauvegarde le chemin original pour une utilisation future
            request.original_path = request.path_info
            # Retire le préfixe du chemin
            request.path_info = request.path_info[len(f'/{url_prefix}'):]  
            # Traite la requête normalement
            return self.get_response(request)
            
        # Si l'URL est exactement égale au préfixe (avec ou sans slash)
        elif request.path_info == f'/{url_prefix}' or request.path_info == f'/{url_prefix}/':
            request.original_path = request.path_info
            request.path_info = '/'
            return self.get_response(request)
        
        # Si l'URL est la racine, on la redirige vers le préfixe
        elif request.path_info == '/' and not request.path_info.startswith('/static/'):
            return HttpResponseRedirect(f'/{url_prefix}/')
            
        # Tout le reste passe normalement
        return self.get_response(request)


# Middleware original de Noethysweb (ne pas supprimer)
class CustomMiddleware:
    """Pour les cookies notamment"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response
