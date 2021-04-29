#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import include, path

from core.views import toc
from core.decorators import secure_ajax
from parametrage.views import organisateur, \
    vacances, calendrier, vacances_importation, feries_fixes, feries_variables, feries_generation, \
    comptes_bancaires, modes_reglements, emetteurs, \
    lots_factures, prefixes_factures, regies, messages_factures, \
    types_pieces, regimes, caisses, types_quotients, categories_travail, secteurs, types_sieste, \
    categories_medicales, types_maladies, types_vaccins, medecins, \
    niveaux_scolaires, ecoles, classes, \
    types_cotisations, unites_cotisations, \
    restaurateurs, menus_categories, menus_legendes, \
    messages_categories, listes_diffusion, \
    types_groupes_activites, \
    activites, activites_generalites, activites_responsables, activites_agrements, activites_groupes, \
    activites_renseignements, activites_unites_conso, activites_unites_remplissage, activites_calendrier, \
    activites_ouvertures, activites_evenements, activites_evenements_tarifs, \
    activites_categories_tarifs, activites_noms_tarifs, activites_tarifs, \
    modeles_documents, modeles_emails, modeles_rappels, \
    questionnaires, adresses_mail, activites_assistant, activites_assistant_sejour, activites_assistant_cantine, \
    activites_assistant_sorties, activites_assistant_stage, activites_assistant_annuelle


urlpatterns = [

    # Table des matières
    path('parametrage/', toc.Toc.as_view(menu_code="parametrage_toc"), name='parametrage_toc'),

    # Organisateur
    path('parametrage/organisateur/ajouter', organisateur.Ajouter.as_view(), name='organisateur_ajouter'),
    path('parametrage/organisateur/modifier/<int:pk>', organisateur.Modifier.as_view(), name='organisateur_modifier'),

    # Groupes d'activités
    path('parametrage/types_groupes_activites/liste', types_groupes_activites.Liste.as_view(), name='types_groupes_activites_liste'),
    path('parametrage/types_groupes_activites/ajouter', types_groupes_activites.Ajouter.as_view(), name='types_groupes_activites_ajouter'),
    path('parametrage/types_groupes_activites/modifier/<int:pk>', types_groupes_activites.Modifier.as_view(), name='types_groupes_activites_modifier'),
    path('parametrage/types_groupes_activites/supprimer/<int:pk>', types_groupes_activites.Supprimer.as_view(), name='types_groupes_activites_supprimer'),

    # Activites
    path('parametrage/activites/liste', activites.Liste.as_view(), name='activites_liste'),
    path('parametrage/activites/ajouter', activites.Ajouter.as_view(), name='activites_ajouter'),
    path('parametrage/activites/supprimer/<int:idactivite>', activites.Supprimer.as_view(), name='activites_supprimer'),
    path('parametrage/activites/resume/<int:idactivite>', activites.Resume.as_view(), name='activites_resume'),

    path('parametrage/activites/generalites/<int:idactivite>', activites_generalites.Modifier.as_view(), name='activites_generalites'),

    path('parametrage/activites/responsables/liste/<int:idactivite>', activites_responsables.Liste.as_view(), name='activites_responsables_liste'),
    path('parametrage/activites/responsables/ajouter/<int:idactivite>', activites_responsables.Ajouter.as_view(), name='activites_responsables_ajouter'),
    path('parametrage/activites/responsables/modifier/<int:idactivite>/<int:pk>', activites_responsables.Modifier.as_view(), name='activites_responsables_modifier'),
    path('parametrage/activites/responsables/supprimer/<int:idactivite>/<int:pk>', activites_responsables.Supprimer.as_view(), name='activites_responsables_supprimer'),

    path('parametrage/activites/agrements/liste/<int:idactivite>', activites_agrements.Liste.as_view(), name='activites_agrements_liste'),
    path('parametrage/activites/agrements/ajouter/<int:idactivite>', activites_agrements.Ajouter.as_view(), name='activites_agrements_ajouter'),
    path('parametrage/activites/agrements/modifier/<int:idactivite>/<int:pk>', activites_agrements.Modifier.as_view(), name='activites_agrements_modifier'),
    path('parametrage/activites/agrements/supprimer/<int:idactivite>/<int:pk>', activites_agrements.Supprimer.as_view(), name='activites_agrements_supprimer'),

    path('parametrage/activites/groupes/liste/<int:idactivite>', activites_groupes.Liste.as_view(), name='activites_groupes_liste'),
    path('parametrage/activites/groupes/ajouter/<int:idactivite>', activites_groupes.Ajouter.as_view(), name='activites_groupes_ajouter'),
    path('parametrage/activites/groupes/modifier/<int:idactivite>/<int:pk>', activites_groupes.Modifier.as_view(), name='activites_groupes_modifier'),
    path('parametrage/activites/groupes/supprimer/<int:idactivite>/<int:pk>', activites_groupes.Supprimer.as_view(), name='activites_groupes_supprimer'),

    path('parametrage/activites/renseignements/<int:idactivite>', activites_renseignements.Modifier.as_view(), name='activites_renseignements'),

    path('parametrage/activites/unites_conso/liste/<int:idactivite>', activites_unites_conso.Liste.as_view(), name='activites_unites_conso_liste'),
    path('parametrage/activites/unites_conso/ajouter/<int:idactivite>', activites_unites_conso.Ajouter.as_view(), name='activites_unites_conso_ajouter'),
    path('parametrage/activites/unites_conso/modifier/<int:idactivite>/<int:pk>', activites_unites_conso.Modifier.as_view(), name='activites_unites_conso_modifier'),
    path('parametrage/activites/unites_conso/supprimer/<int:idactivite>/<int:pk>', activites_unites_conso.Supprimer.as_view(), name='activites_unites_conso_supprimer'),

    path('parametrage/activites/unites_remplissage/liste/<int:idactivite>', activites_unites_remplissage.Liste.as_view(), name='activites_unites_remplissage_liste'),
    path('parametrage/activites/unites_remplissage/ajouter/<int:idactivite>', activites_unites_remplissage.Ajouter.as_view(), name='activites_unites_remplissage_ajouter'),
    path('parametrage/activites/unites_remplissage/modifier/<int:idactivite>/<int:pk>', activites_unites_remplissage.Modifier.as_view(), name='activites_unites_remplissage_modifier'),
    path('parametrage/activites/unites_remplissage/supprimer/<int:idactivite>/<int:pk>', activites_unites_remplissage.Supprimer.as_view(), name='activites_unites_remplissage_supprimer'),

    path('parametrage/activites/calendrier/<int:idactivite>', activites_calendrier.View.as_view(), name='activites_calendrier'),
    path('parametrage/activites/ouvertures/<int:idactivite>', activites_ouvertures.Modifier.as_view(), name='activites_ouvertures'),

    path('parametrage/activites/evenements/liste/<int:idactivite>', activites_evenements.Liste.as_view(), name='activites_evenements_liste'),
    path('parametrage/activites/evenements/ajouter/<int:idactivite>', activites_evenements.Ajouter.as_view(), name='activites_evenements_ajouter'),
    path('parametrage/activites/evenements/modifier/<int:idactivite>/<int:pk>', activites_evenements.Modifier.as_view(), name='activites_evenements_modifier'),
    path('parametrage/activites/evenements/supprimer/<int:idactivite>/<int:pk>', activites_evenements.Supprimer.as_view(), name='activites_evenements_supprimer'),

    path('parametrage/activites/tarifs_evenements/liste/<int:idactivite>/<int:evenement>', activites_evenements_tarifs.Liste.as_view(), name='activites_evenements_tarifs_liste'),
    path('parametrage/activites/tarifs_evenements/ajouter/<int:idactivite>/<int:evenement>', activites_evenements_tarifs.Ajouter.as_view(), name='activites_evenements_tarifs_ajouter'),
    path('parametrage/activites/tarifs_evenements/modifier/<int:idactivite>/<int:evenement>/<int:pk>', activites_evenements_tarifs.Modifier.as_view(), name='activites_evenements_tarifs_modifier'),
    path('parametrage/activites/tarifs_evenements/supprimer/<int:idactivite>/<int:evenement>/<int:pk>', activites_evenements_tarifs.Supprimer.as_view(), name='activites_evenements_tarifs_supprimer'),
    path('parametrage/activites/tarifs_evenements/dupliquer/<int:idactivite>/<int:evenement>/<int:pk>', activites_evenements_tarifs.Dupliquer.as_view(), name='activites_evenements_tarifs_dupliquer'),

    path('parametrage/activites/categories_tarifs/liste/<int:idactivite>', activites_categories_tarifs.Liste.as_view(), name='activites_categories_tarifs_liste'),
    path('parametrage/activites/categories_tarifs/ajouter/<int:idactivite>', activites_categories_tarifs.Ajouter.as_view(), name='activites_categories_tarifs_ajouter'),
    path('parametrage/activites/categories_tarifs/modifier/<int:idactivite>/<int:pk>', activites_categories_tarifs.Modifier.as_view(), name='activites_categories_tarifs_modifier'),
    path('parametrage/activites/categories_tarifs/supprimer/<int:idactivite>/<int:pk>', activites_categories_tarifs.Supprimer.as_view(), name='activites_categories_tarifs_supprimer'),

    path('parametrage/activites/noms_tarifs/liste/<int:idactivite>', activites_noms_tarifs.Liste.as_view(), name='activites_noms_tarifs_liste'),
    path('parametrage/activites/noms_tarifs/ajouter/<int:idactivite>', activites_noms_tarifs.Ajouter.as_view(), name='activites_noms_tarifs_ajouter'),
    path('parametrage/activites/noms_tarifs/modifier/<int:idactivite>/<int:pk>', activites_noms_tarifs.Modifier.as_view(), name='activites_noms_tarifs_modifier'),
    path('parametrage/activites/noms_tarifs/supprimer/<int:idactivite>/<int:pk>', activites_noms_tarifs.Supprimer.as_view(), name='activites_noms_tarifs_supprimer'),

    path('parametrage/activites/tarifs/liste/<int:idactivite>', activites_tarifs.Liste.as_view(), name='activites_tarifs_liste'),
    path('parametrage/activites/tarifs/liste/<int:idactivite>/<int:categorie>', activites_tarifs.Liste.as_view(), name='activites_tarifs_liste'),
    path('parametrage/activites/tarifs/ajouter/<int:idactivite>/<int:categorie>', activites_tarifs.Ajouter.as_view(), name='activites_tarifs_ajouter'),
    path('parametrage/activites/tarifs/modifier/<int:idactivite>/<int:categorie>/<int:pk>', activites_tarifs.Modifier.as_view(), name='activites_tarifs_modifier'),
    path('parametrage/activites/tarifs/supprimer/<int:idactivite>/<int:categorie>/<int:pk>', activites_tarifs.Supprimer.as_view(), name='activites_tarifs_supprimer'),
    path('parametrage/activites/tarifs/dupliquer/<int:idactivite>/<int:categorie>/<int:pk>', activites_tarifs.Dupliquer.as_view(), name='activites_tarifs_dupliquer'),

    # Assistant de paramétrage
    path('parametrage/activites/assistant/liste', activites_assistant.Liste.as_view(), name='activites_assistant_liste'),
    path('parametrage/activites/assistant/sejour', activites_assistant_sejour.Assistant.as_view(), name='activites_assistant_sejour'),
    path('parametrage/activites/assistant/cantine', activites_assistant_cantine.Assistant.as_view(), name='activites_assistant_cantine'),
    path('parametrage/activites/assistant/sorties', activites_assistant_sorties.Assistant.as_view(), name='activites_assistant_sorties'),
    path('parametrage/activites/assistant/stages', activites_assistant_stage.Assistant.as_view(), name='activites_assistant_stage'),
    path('parametrage/activites/assistant/annuelle', activites_assistant_annuelle.Assistant.as_view(), name='activites_assistant_annuelle'),

    # Types de cotisations
    path('parametrage/types_cotisations/liste', types_cotisations.Liste.as_view(), name='types_cotisations_liste'),
    path('parametrage/types_cotisations/ajouter', types_cotisations.Ajouter.as_view(), name='types_cotisations_ajouter'),
    path('parametrage/types_cotisations/modifier/<int:pk>', types_cotisations.Modifier.as_view(), name='types_cotisations_modifier'),
    path('parametrage/types_cotisations/supprimer/<int:pk>', types_cotisations.Supprimer.as_view(), name='types_cotisations_supprimer'),

    # Unités de cotisations
    path('parametrage/unites_cotisations/liste', unites_cotisations.Liste.as_view(), name='unites_cotisations_liste'),
    path('parametrage/unites_cotisations/liste/<int:categorie>', unites_cotisations.Liste.as_view(), name='unites_cotisations_liste'),
    path('parametrage/unites_cotisations/ajouter/<int:categorie>', unites_cotisations.Ajouter.as_view(), name='unites_cotisations_ajouter'),
    path('parametrage/unites_cotisations/modifier/<int:categorie>/<int:pk>', unites_cotisations.Modifier.as_view(), name='unites_cotisations_modifier'),
    path('parametrage/unites_cotisations/supprimer/<int:categorie>/<int:pk>', unites_cotisations.Supprimer.as_view(), name='unites_cotisations_supprimer'),

    # Comptes bancaires
    path('parametrage/comptes_bancaires/liste', comptes_bancaires.Liste.as_view(), name='comptes_bancaires_liste'),
    path('parametrage/comptes_bancaires/ajouter', comptes_bancaires.Ajouter.as_view(), name='comptes_bancaires_ajouter'),
    path('parametrage/comptes_bancaires/modifier/<int:pk>', comptes_bancaires.Modifier.as_view(), name='comptes_bancaires_modifier'),
    path('parametrage/comptes_bancaires/supprimer/<int:pk>', comptes_bancaires.Supprimer.as_view(), name='comptes_bancaires_supprimer'),

    # Modes de règlements
    path('parametrage/modes_reglements/liste', modes_reglements.Liste.as_view(), name='modes_reglements_liste'),
    path('parametrage/modes_reglements/ajouter', modes_reglements.Ajouter.as_view(), name='modes_reglements_ajouter'),
    path('parametrage/modes_reglements/modifier/<int:pk>', modes_reglements.Modifier.as_view(), name='modes_reglements_modifier'),
    path('parametrage/modes_reglements/supprimer/<int:pk>', modes_reglements.Supprimer.as_view(), name='modes_reglements_supprimer'),

    # Emetteurs
    path('parametrage/emetteurs/liste', emetteurs.Liste.as_view(), name='emetteurs_liste'),
    path('parametrage/emetteurs/ajouter', emetteurs.Ajouter.as_view(), name='emetteurs_ajouter'),
    path('parametrage/emetteurs/modifier/<int:pk>', emetteurs.Modifier.as_view(), name='emetteurs_modifier'),
    path('parametrage/emetteurs/supprimer/<int:pk>', emetteurs.Supprimer.as_view(), name='emetteurs_supprimer'),

    # Lots de factures
    path('parametrage/lots_factures/liste', lots_factures.Liste.as_view(), name='lots_factures_liste'),
    path('parametrage/lots_factures/ajouter', lots_factures.Ajouter.as_view(), name='lots_factures_ajouter'),
    path('parametrage/lots_factures/modifier/<int:pk>', lots_factures.Modifier.as_view(), name='lots_factures_modifier'),
    path('parametrage/lots_factures/supprimer/<int:pk>', lots_factures.Supprimer.as_view(), name='lots_factures_supprimer'),

    # Préfixes de factures
    path('parametrage/prefixes_factures/liste', prefixes_factures.Liste.as_view(), name='prefixes_factures_liste'),
    path('parametrage/prefixes_factures/ajouter', prefixes_factures.Ajouter.as_view(), name='prefixes_factures_ajouter'),
    path('parametrage/prefixes_factures/modifier/<int:pk>', prefixes_factures.Modifier.as_view(), name='prefixes_factures_modifier'),
    path('parametrage/prefixes_factures/supprimer/<int:pk>', prefixes_factures.Supprimer.as_view(), name='prefixes_factures_supprimer'),

    # Messages de facture
    path('parametrage/messages_factures/liste', messages_factures.Liste.as_view(), name='messages_factures_liste'),
    path('parametrage/messages_factures/ajouter', messages_factures.Ajouter.as_view(), name='messages_factures_ajouter'),
    path('parametrage/messages_factures/modifier/<int:pk>', messages_factures.Modifier.as_view(), name='messages_factures_modifier'),
    path('parametrage/messages_factures/supprimer/<int:pk>', messages_factures.Supprimer.as_view(), name='messages_factures_supprimer'),

    # Régies
    path('parametrage/regies/liste', regies.Liste.as_view(), name='regies_liste'),
    path('parametrage/regies/ajouter', regies.Ajouter.as_view(), name='regies_ajouter'),
    path('parametrage/regies/modifier/<int:pk>', regies.Modifier.as_view(), name='regies_modifier'),
    path('parametrage/regies/supprimer/<int:pk>', regies.Supprimer.as_view(), name='regies_supprimer'),

    # Types de pièces
    path('parametrage/types_pieces/liste', types_pieces.Liste.as_view(), name='types_pieces_liste'),
    path('parametrage/types_pieces/ajouter', types_pieces.Ajouter.as_view(), name='types_pieces_ajouter'),
    path('parametrage/types_pieces/modifier/<int:pk>', types_pieces.Modifier.as_view(), name='types_pieces_modifier'),
    path('parametrage/types_pieces/supprimer/<int:pk>', types_pieces.Supprimer.as_view(), name='types_pieces_supprimer'),

    # Régimes
    path('parametrage/regimes/liste', regimes.Liste.as_view(), name='regimes_liste'),
    path('parametrage/regimes/ajouter', regimes.Ajouter.as_view(), name='regimes_ajouter'),
    path('parametrage/regimes/modifier/<int:pk>', regimes.Modifier.as_view(), name='regimes_modifier'),
    path('parametrage/regimes/supprimer/<int:pk>', regimes.Supprimer.as_view(), name='regimes_supprimer'),

    # Caisses
    path('parametrage/caisses/liste', caisses.Liste.as_view(), name='caisses_liste'),
    path('parametrage/caisses/ajouter', caisses.Ajouter.as_view(), name='caisses_ajouter'),
    path('parametrage/caisses/modifier/<int:pk>', caisses.Modifier.as_view(), name='caisses_modifier'),
    path('parametrage/caisses/supprimer/<int:pk>', caisses.Supprimer.as_view(), name='caisses_supprimer'),

    # Types de quotients
    path('parametrage/types_quotients/liste', types_quotients.Liste.as_view(), name='types_quotients_liste'),
    path('parametrage/types_quotients/ajouter', types_quotients.Ajouter.as_view(), name='types_quotients_ajouter'),
    path('parametrage/types_quotients/modifier/<int:pk>', types_quotients.Modifier.as_view(), name='types_quotients_modifier'),
    path('parametrage/types_quotients/supprimer/<int:pk>', types_quotients.Supprimer.as_view(), name='types_quotients_supprimer'),

    # Catégorie professionnelles
    path('parametrage/categories_travail/liste', categories_travail.Liste.as_view(), name='categories_travail_liste'),
    path('parametrage/categories_travail/ajouter', categories_travail.Ajouter.as_view(), name='categories_travail_ajouter'),
    path('parametrage/categories_travail/modifier/<int:pk>', categories_travail.Modifier.as_view(), name='categories_travail_modifier'),
    path('parametrage/categories_travail/supprimer/<int:pk>', categories_travail.Supprimer.as_view(), name='categories_travail_supprimer'),

    # Secteurs géographiques
    path('parametrage/secteurs/liste', secteurs.Liste.as_view(), name='secteurs_liste'),
    path('parametrage/secteurs/ajouter', secteurs.Ajouter.as_view(), name='secteurs_ajouter'),
    path('parametrage/secteurs/modifier/<int:pk>', secteurs.Modifier.as_view(), name='secteurs_modifier'),
    path('parametrage/secteurs/supprimer/<int:pk>', secteurs.Supprimer.as_view(), name='secteurs_supprimer'),

    # Types de sieste
    path('parametrage/types_sieste/liste', types_sieste.Liste.as_view(), name='types_sieste_liste'),
    path('parametrage/types_sieste/ajouter', types_sieste.Ajouter.as_view(), name='types_sieste_ajouter'),
    path('parametrage/types_sieste/modifier/<int:pk>', types_sieste.Modifier.as_view(), name='types_sieste_modifier'),
    path('parametrage/types_sieste/supprimer/<int:pk>', types_sieste.Supprimer.as_view(), name='types_sieste_supprimer'),

    # Catégories médicales
    path('parametrage/categories_medicales/liste', categories_medicales.Liste.as_view(), name='categories_medicales_liste'),
    path('parametrage/categories_medicales/ajouter', categories_medicales.Ajouter.as_view(), name='categories_medicales_ajouter'),
    path('parametrage/categories_medicales/modifier/<int:pk>', categories_medicales.Modifier.as_view(), name='categories_medicales_modifier'),
    path('parametrage/categories_medicales/supprimer/<int:pk>', categories_medicales.Supprimer.as_view(), name='categories_medicales_supprimer'),

    # Catégories médicales
    path('parametrage/types_maladies/liste', types_maladies.Liste.as_view(), name='types_maladies_liste'),
    path('parametrage/types_maladies/ajouter', types_maladies.Ajouter.as_view(), name='types_maladies_ajouter'),
    path('parametrage/types_maladies/modifier/<int:pk>', types_maladies.Modifier.as_view(), name='types_maladies_modifier'),
    path('parametrage/types_maladies/supprimer/<int:pk>', types_maladies.Supprimer.as_view(), name='types_maladies_supprimer'),

    # Types de vaccins
    path('parametrage/types_vaccins/liste', types_vaccins.Liste.as_view(), name='types_vaccins_liste'),
    path('parametrage/types_vaccins/ajouter', types_vaccins.Ajouter.as_view(), name='types_vaccins_ajouter'),
    path('parametrage/types_vaccins/modifier/<int:pk>', types_vaccins.Modifier.as_view(), name='types_vaccins_modifier'),
    path('parametrage/types_vaccins/supprimer/<int:pk>', types_vaccins.Supprimer.as_view(), name='types_vaccins_supprimer'),

    # Médecins
    path('parametrage/medecins/liste', medecins.Liste.as_view(), name='medecins_liste'),
    path('parametrage/medecins/ajouter', medecins.Ajouter.as_view(), name='medecins_ajouter'),
    path('parametrage/medecins/modifier/<int:pk>', medecins.Modifier.as_view(),name='medecins_modifier'),
    path('parametrage/medecins/supprimer/<int:pk>', medecins.Supprimer.as_view(),name='medecins_supprimer'),

    # Niveaux scolaires
    path('parametrage/niveaux_scolaires/liste', niveaux_scolaires.Liste.as_view(), name='niveaux_scolaires_liste'),
    path('parametrage/niveaux_scolaires/ajouter', niveaux_scolaires.Ajouter.as_view(), name='niveaux_scolaires_ajouter'),
    path('parametrage/niveaux_scolaires/modifier/<int:pk>', niveaux_scolaires.Modifier.as_view(), name='niveaux_scolaires_modifier'),
    path('parametrage/niveaux_scolaires/supprimer/<int:pk>', niveaux_scolaires.Supprimer.as_view(), name='niveaux_scolaires_supprimer'),

    # Ecoles
    path('parametrage/ecoles/liste', ecoles.Liste.as_view(), name='ecoles_liste'),
    path('parametrage/ecoles/ajouter', ecoles.Ajouter.as_view(), name='ecoles_ajouter'),
    path('parametrage/ecoles/modifier/<int:pk>', ecoles.Modifier.as_view(), name='ecoles_modifier'),
    path('parametrage/ecoles/supprimer/<int:pk>', ecoles.Supprimer.as_view(), name='ecoles_supprimer'),

    # Classes
    path('parametrage/classes/liste', classes.Liste.as_view(), name='classes_liste'),
    path('parametrage/classes/ajouter', classes.Ajouter.as_view(), name='classes_ajouter'),
    path('parametrage/classes/modifier/<int:pk>', classes.Modifier.as_view(), name='classes_modifier'),
    path('parametrage/classes/supprimer/<int:pk>', classes.Supprimer.as_view(), name='classes_supprimer'),

    # Restaurateurs
    path('parametrage/restaurateurs/liste', restaurateurs.Liste.as_view(), name='restaurateurs_liste'),
    path('parametrage/restaurateurs/ajouter', restaurateurs.Ajouter.as_view(), name='restaurateurs_ajouter'),
    path('parametrage/restaurateurs/modifier/<int:pk>', restaurateurs.Modifier.as_view(), name='restaurateurs_modifier'),
    path('parametrage/restaurateurs/supprimer/<int:pk>', restaurateurs.Supprimer.as_view(), name='restaurateurs_supprimer'),

    # Catégories de menus
    path('parametrage/menus_categories/liste', menus_categories.Liste.as_view(), name='menus_categories_liste'),
    path('parametrage/menus_categories/ajouter', menus_categories.Ajouter.as_view(), name='menus_categories_ajouter'),
    path('parametrage/menus_categories/modifier/<int:pk>', menus_categories.Modifier.as_view(), name='menus_categories_modifier'),
    path('parametrage/menus_categories/supprimer/<int:pk>', menus_categories.Supprimer.as_view(), name='menus_categories_supprimer'),

    # Légendes de menus
    path('parametrage/menus_legendes/liste', menus_legendes.Liste.as_view(), name='menus_legendes_liste'),
    path('parametrage/menus_legendes/ajouter', menus_legendes.Ajouter.as_view(), name='menus_legendes_ajouter'),
    path('parametrage/menus_legendes/modifier/<int:pk>', menus_legendes.Modifier.as_view(), name='menus_legendes_modifier'),
    path('parametrage/menus_legendes/supprimer/<int:pk>', menus_legendes.Supprimer.as_view(), name='menus_legendes_supprimer'),

    # Catégories de messages
    path('parametrage/messages_categories/liste', messages_categories.Liste.as_view(), name='messages_categories_liste'),
    path('parametrage/messages_categories/ajouter', messages_categories.Ajouter.as_view(), name='messages_categories_ajouter'),
    path('parametrage/messages_categories/modifier/<int:pk>', messages_categories.Modifier.as_view(), name='messages_categories_modifier'),
    path('parametrage/messages_categories/supprimer/<int:pk>', messages_categories.Supprimer.as_view(), name='messages_categories_supprimer'),

    # Listes de diffusion
    path('parametrage/listes_diffusion/liste', listes_diffusion.Liste.as_view(), name='listes_diffusion_liste'),
    path('parametrage/listes_diffusion/ajouter', listes_diffusion.Ajouter.as_view(), name='listes_diffusion_ajouter'),
    path('parametrage/listes_diffusion/modifier/<int:pk>', listes_diffusion.Modifier.as_view(), name='listes_diffusion_modifier'),
    path('parametrage/listes_diffusion/supprimer/<int:pk>', listes_diffusion.Supprimer.as_view(), name='listes_diffusion_supprimer'),

    # Périodes de vacances
    path('parametrage/vacances/liste', vacances.Liste.as_view(), name='vacances_liste'),
    path('parametrage/vacances/ajouter', vacances.Ajouter.as_view(), name='vacances_ajouter'),
    path('parametrage/vacances/modifier/<int:pk>', vacances.Modifier.as_view(), name='vacances_modifier'),
    path('parametrage/vacances/supprimer/<int:pk>', vacances.Supprimer.as_view(), name='vacances_supprimer'),

    path('parametrage/vacances_importation/<str:zone>', vacances_importation.View.as_view(), name='vacances_importation'),

    # Jours fériés fixes
    path('parametrage/feries_fixes/liste', feries_fixes.Liste.as_view(), name='feries_fixes_liste'),
    path('parametrage/feries_fixes/ajouter', feries_fixes.Ajouter.as_view(), name='feries_fixes_ajouter'),
    path('parametrage/feries_fixes/modifier/<int:pk>', feries_fixes.Modifier.as_view(), name='feries_fixes_modifier'),
    path('parametrage/feries_fixes/supprimer/<int:pk>', feries_fixes.Supprimer.as_view(), name='feries_fixes_supprimer'),

    # Jours fériés variables
    path('parametrage/feries_variables/liste', feries_variables.Liste.as_view(), name='feries_variables_liste'),
    path('parametrage/feries_variables/ajouter', feries_variables.Ajouter.as_view(), name='feries_variables_ajouter'),
    path('parametrage/feries_variables/modifier/<int:pk>', feries_variables.Modifier.as_view(), name='feries_variables_modifier'),
    path('parametrage/feries_variables/supprimer/<int:pk>', feries_variables.Supprimer.as_view(), name='feries_variables_supprimer'),

    path('parametrage/feries_generation', feries_generation.View.as_view(), name='feries_generation'),

    # Modèles de documents
    path('parametrage/modeles_documents/liste', modeles_documents.Liste.as_view(), name='modeles_documents_liste'),
    path('parametrage/modeles_documents/liste/<str:categorie>', modeles_documents.Liste.as_view(), name='modeles_documents_liste'),
    path('parametrage/modeles_documents/ajouter/<str:nom>/<str:categorie>', modeles_documents.Ajouter.as_view(), name='modeles_documents_ajouter'),
    path('parametrage/modeles_documents/modifier/<str:categorie>/<int:pk>', modeles_documents.Modifier.as_view(), name='modeles_documents_modifier'),
    path('parametrage/modeles_documents/supprimer/<str:categorie>/<int:pk>', modeles_documents.Supprimer.as_view(), name='modeles_documents_supprimer'),
    path('parametrage/modeles_documents/dupliquer/<str:categorie>/<int:pk>', modeles_documents.Dupliquer.as_view(), name='modeles_documents_dupliquer'),
    path('parametrage/modeles_documents/creer/<str:categorie>', modeles_documents.Creer.as_view(), name='modeles_documents_creer'),

    # Modèles d'emails
    path('parametrage/modeles_emails/liste', modeles_emails.Liste.as_view(), name='modeles_emails_liste'),
    path('parametrage/modeles_emails/liste/<str:categorie>', modeles_emails.Liste.as_view(), name='modeles_emails_liste'),
    path('parametrage/modeles_emails/ajouter/<str:categorie>', modeles_emails.Ajouter.as_view(), name='modeles_emails_ajouter'),
    path('parametrage/modeles_emails/modifier/<str:categorie>/<int:pk>', modeles_emails.Modifier.as_view(), name='modeles_emails_modifier'),
    path('parametrage/modeles_emails/supprimer/<str:categorie>/<int:pk>', modeles_emails.Supprimer.as_view(), name='modeles_emails_supprimer'),
    path('parametrage/modeles_emails/dupliquer/<str:categorie>/<int:pk>', modeles_emails.Dupliquer.as_view(), name='modeles_emails_dupliquer'),

    # Modèles de lettres de rappel
    path('parametrage/modeles_rappels/liste', modeles_rappels.Liste.as_view(), name='modeles_rappels_liste'),
    path('parametrage/modeles_rappels/ajouter', modeles_rappels.Ajouter.as_view(), name='modeles_rappels_ajouter'),
    path('parametrage/modeles_rappels/modifier/<int:pk>', modeles_rappels.Modifier.as_view(), name='modeles_rappels_modifier'),
    path('parametrage/modeles_rappels/supprimer/<int:pk>', modeles_rappels.Supprimer.as_view(), name='modeles_rappels_supprimer'),
    path('parametrage/modeles_rappels/dupliquer/<int:pk>', modeles_rappels.Dupliquer.as_view(), name='modeles_rappels_dupliquer'),

    # Questions des questionnaires
    path('parametrage/questions/liste', questionnaires.Liste.as_view(), name='questions_liste'),
    path('parametrage/questions/liste/<str:categorie>', questionnaires.Liste.as_view(), name='questions_liste'),
    path('parametrage/questions/ajouter/<str:categorie>', questionnaires.Ajouter.as_view(), name='questions_ajouter'),
    path('parametrage/questions/modifier/<str:categorie>/<int:pk>', questionnaires.Modifier.as_view(), name='questions_modifier'),
    path('parametrage/questions/supprimer/<str:categorie>/<int:pk>', questionnaires.Supprimer.as_view(), name='questions_supprimer'),

    # Adresses mail
    path('parametrage/adresses_mail/liste', adresses_mail.Liste.as_view(), name='adresses_mail_liste'),
    path('parametrage/adresses_mail/ajouter', adresses_mail.Ajouter.as_view(), name='adresses_mail_ajouter'),
    path('parametrage/adresses_mail/modifier/<int:pk>', adresses_mail.Modifier.as_view(), name='adresses_mail_modifier'),
    path('parametrage/adresses_mail/supprimer/<int:pk>', adresses_mail.Supprimer.as_view(), name='adresses_mail_supprimer'),



    # AJAX
    path('parametrage/get_calendrier', secure_ajax(calendrier.Get_calendrier), name='ajax_get_calendrier'),
    path('parametrage/niveaux_scolaires/deplacer_lignes', secure_ajax(niveaux_scolaires.Deplacer.as_view()), name='ajax_deplacer_lignes_niveaux_scolaires'),
    path('parametrage/menus_categories/deplacer_lignes', secure_ajax(menus_categories.Deplacer.as_view()), name='ajax_deplacer_lignes_menus_categories'),
    path('parametrage/activites/groupes/liste/deplacer_lignes', secure_ajax(activites_groupes.Deplacer.as_view()), name='ajax_deplacer_lignes_activites_groupes'),
    path('parametrage/activites/unites_conso/liste/deplacer_lignes', secure_ajax(activites_unites_conso.Deplacer.as_view()), name='ajax_deplacer_lignes_activites_unites_conso'),
    path('parametrage/activites/unites_remplissage/liste/deplacer_lignes', secure_ajax(activites_unites_remplissage.Deplacer.as_view()), name='ajax_deplacer_lignes_activites_unites_remplissage'),
    path('parametrage/get_calendrier_ouvertures', secure_ajax(activites_ouvertures.Get_calendrier_ouvertures), name='ajax_get_calendrier_ouvertures'),
    path('parametrage/traitement_lot_ouvertures', secure_ajax(activites_ouvertures.Traitement_lot_ouvertures), name='ajax_traitement_lot_ouvertures'),
    path('parametrage/valider_calendrier_ouvertures', secure_ajax(activites_ouvertures.Valider_calendrier_ouvertures), name='ajax_valider_calendrier_ouvertures'),
    path('parametrage/get_fond_modele', secure_ajax(modeles_documents.Get_fond_modele), name='ajax_get_fond_modele'),
    path('parametrage/export_svg', secure_ajax(modeles_documents.Export_svg), name='ajax_export_svg'),
    path('parametrage/questions/deplacer_lignes', secure_ajax(questionnaires.Deplacer.as_view()), name='ajax_deplacer_lignes_questionnaires'),
    path('parametrage/adresses_mail/envoyer_mail_test', secure_ajax(adresses_mail.Envoyer_mail_test), name='ajax_envoyer_mail_test'),


]