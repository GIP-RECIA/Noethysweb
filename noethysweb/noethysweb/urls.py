#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.contrib.staticfiles import views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from core.views import erreurs

# Import optionnel pour le debug toolbar (utilisé uniquement si DEBUG=True)
if settings.DEBUG:
    import debug_toolbar

# Définir les patterns de base
urlpatterns = [
    path(settings.URL_GESTION, admin.site.urls),
    path(settings.URL_BUREAU, include('core.urls')),
    path(settings.URL_BUREAU, include('parametrage.urls')),
    path(settings.URL_BUREAU, include('outils.urls')),
    path(settings.URL_BUREAU, include('individus.urls')),
    path(settings.URL_BUREAU, include('fiche_famille.urls')),
    path(settings.URL_BUREAU, include('fiche_individu.urls')),
    path(settings.URL_BUREAU, include('cotisations.urls')),
    path(settings.URL_BUREAU, include('locations.urls')),
    path(settings.URL_BUREAU, include('consommations.urls')),
    path(settings.URL_BUREAU, include('facturation.urls')),
    path(settings.URL_BUREAU, include('reglements.urls')),
    path(settings.URL_BUREAU, include('comptabilite.urls')),
    path(settings.URL_BUREAU, include('collaborateurs.urls')),
    path(settings.URL_BUREAU, include('aide.urls')),
    path('select2/', include('django_select2.urls')),
    path('summernote/', include('django_summernote.urls')),
    path('captcha/', include('captcha.urls')),
    path('locked/', erreurs.erreur_axes, name="locked_out"),
    path('deblocage/<str:code>', erreurs.deblocage, name="deblocage"),
]

# URL pour le sélecteur de traduction
urlpatterns += [
    path("i18n/", include("django.conf.urls.i18n"))
]

# Intégration des plugins
for nom_plugin in settings.PLUGINS:
    urlpatterns.append(path(settings.URL_BUREAU, include("plugins.%s.urls" % nom_plugin)))

# Ajout de l'URL du portail
if settings.PORTAIL_ACTIF:
    urlpatterns.append(path(settings.URL_PORTAIL, include('portail.urls')))

if settings.DEBUG:
    # Ajoute le debugtoolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
    
    # Ajoute le répertoire Media pour le développement
    # Modification pour prendre en compte URL_ROOT dans les chemins media
    if settings.URL_ROOT:
        # Pour les fichiers média avec URL_ROOT
        # Ajout d'un pattern sans le préfixe URL_ROOT pour gérer le cas où le middleware l'a retiré
        urlpatterns += [
            # Pattern pour les chemins avec le préfixe URL_ROOT
            re_path(r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'), serve, {'document_root': settings.MEDIA_ROOT}),
            # Pattern pour les chemins sans le préfixe URL_ROOT (après traitement par le middleware)
            re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        ]
    else:
        # Configuration standard pour les fichiers média sans URL_ROOT
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
    # Configuration des fichiers statiques pour qu'ils respectent le préfixe URL_ROOT
    
    # Désactiver tous les patterns de fichiers statiques existants
    # pour éviter les conflits avec notre configuration personalisée
    
    # Ajoute manuellement la configuration pour servir les fichiers statiques
    if settings.URL_ROOT:
        # Pour le cas avec URL_ROOT, on utilise le STATIC_URL configuré dans settings.py
        # qui inclut déjà URL_ROOT
        urlpatterns += [
            re_path(r'^%s(?P<path>.*)$' % settings.STATIC_URL.lstrip('/'), views.serve, {'document_root': settings.STATIC_ROOT}),
        ]
    else:
        # Pour le cas sans URL_ROOT, on utilise la configuration standard de Django
        urlpatterns += staticfiles_urlpatterns()

# Le middleware URLPrefixMiddleware gère déjà le préfixe URL_ROOT pour les URL normales


# Modifie les noms dans l'admin
admin.site.site_header = "Administration de Noethysweb"
admin.site.index_title = "Noethysweb"
admin.site.site_title = "Administration"

# Personnalisation des pages d'erreur
handler403 = erreurs.erreur_403
handler404 = erreurs.erreur_404
handler500 = erreurs.erreur_500
