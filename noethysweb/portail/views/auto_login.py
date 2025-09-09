from django.shortcuts import render, redirect
from django.contrib.auth import login, get_user_model
from django.http import HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from django.conf import settings
import jwt
from datetime import datetime, timedelta
from django.urls import reverse_lazy

User = get_user_model()

class AutoLoginView(View):
    """
    Vue pour l'authentification automatique depuis une autre application avec JWT
    """
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def get(self, request):
        """Traitement de l'authentification automatique avec JWT"""
        
        # 1. Récupérer le token JWT
        token = request.GET.get("token")
        if not token:
            return redirect("/")
        
        try:
            # 2. Décoder et vérifier le token
            payload = jwt.decode(token, settings.SSO_SECRET_KEY, algorithms=["HS256"])
            
            # 3. Extraire les données utilisateur
            username = payload["username"]
            email = payload["email"]
            
            # Données optionnelles
            first_name = payload.get("first_name", "")
            last_name = payload.get("last_name", "")

        except jwt.InvalidTokenError:
            return redirect("/")
        except KeyError:
            # Si des champs obligatoires manquent dans le payload
            return redirect("/")
        
        # 4. Chercher ou créer l'utilisateur
        # try:
        user = self._get_or_create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        # 5. Connecter automatiquement l'utilisateur
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        # 6. Redirection
        return redirect(reverse_lazy("portail_accueil"))
            
        # except Exception as e:
        #     # Log l'erreur en production
        #     print(f"Erreur lors de la connexion automatique: {str(e)}")
        #     return redirect("/")
    
    def _get_or_create_user(self, username, email, first_name="", last_name=""):
        """
        Récupérer un utilisateur existant ou en créer un nouveau
        """
        try:
            # Chercher d'abord par email (plus fiable)
            print("///////")
            print(username)
            print("///////")
            user = User.objects.get(username=username)
            # Mettre à jour les informations si nécessaire
            updated = False
            if first_name and not user.first_name:
                user.first_name = first_name
                updated = True
            if last_name and not user.last_name:
                user.last_name = last_name
                updated = True
            if updated:
                user.save()
            
            return user
            
        except User.DoesNotExist:
            # Créer un nouvel utilisateur
            
            # S'assurer que le username est unique
            original_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{original_username}_{counter}"
                counter += 1
            
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            return user