# -*- coding: utf-8 -*-
#  Copyright (c) 2024-2025 Faouzia TEKAYA.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from core.models import PortailParametre


class Parametre():
    def __init__(self, *args, **kwargs):
        self.code = kwargs.get("code", None)
        self.label = kwargs.get("label", None)
        self.type = kwargs.get("type", None)
        self.valeur = kwargs.get("valeur", None)
        self.help_text = kwargs.get("help_text", None)
        self.required = kwargs.get("required", False)
        self.choix = kwargs.get("choix", [])

    def Get_ctrl(self):
        if self.type == "boolean":
            return forms.BooleanField(label=self.label, required=self.required, help_text=self.help_text)
        elif self.type == "choice":
            return forms.ChoiceField(label=self.label, required=self.required, 
                                   choices=self.choix, widget=forms.RadioSelect, 
                                   help_text=self.help_text)

    def From_db(self, valeur=""):
        if self.type == "boolean":
            self.valeur = valeur == "True"
        else:
            self.valeur = valeur


LISTE_PARAMETRES = [

   # Fiche Individu
    Parametre(code="questionnaire_afficher_page_individu", label="Afficher la page Questionnaire", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Questionnaire sur la fiche Individu."),
    Parametre(code="liens_afficher_page_individu", label="Afficher la page Liens", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Liens sur la fiche Individu."),
    Parametre(code="regimes_alimentaires_afficher_page_individu", label="Afficher la page Régimes alimentaires", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Régimes alimentaires sur la fiche Individu."),
    Parametre(code="maladies_afficher_page_individu", label="Afficher la page Maladies", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Maladies sur la fiche Individu."),
    Parametre(code="medical_afficher_page_individu", label="Afficher la page Médical", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Médical sur la fiche Individu."),
    Parametre(code="assurances_afficher_page_individu", label="Afficher la page Assurances", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Assurances sur la fiche Individu."),
    Parametre(code="contacts_afficher_page_individu", label="Afficher la page Contacts", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Contacts sur la fiche Individu."),
    Parametre(code="transports_afficher_page_individu", label="Afficher la page Transports", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Transports sur la fiche Individu."),
    Parametre(code="consommations_afficher_page_individu", label="Afficher la page Consommations", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Consommations sur la fiche Individu."),

    # Fiche Famille
    Parametre(code="questionnaire_afficher_page_famille", label="Afficher la page Questionnaire", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Questionnaire sur la fiche Famille."),
    Parametre(code="pieces_afficher_page_famille", label="Afficher la page Pièces", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Pièces sur la fiche Famille."),
    Parametre(code="locations_afficher_page_famille", label="Afficher la page Locations", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Locations sur la fiche Famille."),
    Parametre(code="cotisations_afficher_page_famille", label="Afficher la page Adhésions", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Adhésions sur la fiche Famille."),
    Parametre(code="caisse_afficher_page_famille", label="Afficher la page Caisse", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Caisse sur la fiche Famille."),
    Parametre(code="aides_afficher_page_famille", label="Afficher la page Aides", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Aides sur la fiche Famille."),
    Parametre(code="quotients_afficher_page_famille", label="Afficher la page Quotients familiaux", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Quotients familiaux sur la fiche Famille."),
    Parametre(code="prestations_afficher_page_famille", label="Afficher la page Prestations", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Prestations sur la fiche Famille."),
    Parametre(code="factures_afficher_page_famille", label="Afficher la page Factures", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Factures sur la fiche Famille."),
    Parametre(code="reglements_afficher_page_famille", label="Afficher la page Règlements", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Règlements sur la fiche Famille."),
    Parametre(code="messagerie_afficher_page_famille", label="Afficher la page Messagerie", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Messagerie sur la fiche Famille."),
    Parametre(code="outils_afficher_page_famille", label="Afficher la page Outils", type="boolean",valeur=True, help_text="Cochez cette case pour afficher la page Outils sur la fiche Famille."),
    Parametre(code="consommations_afficher_page_famille", label="Afficher la page Consommations", type="boolean", valeur=True, help_text="Cochez cette case pour afficher la page Consommations sur la fiche Famille."),

]


def Get_dict_parametres():
    """ Renvoi un dict code: valeur des paramètres """
    dict_parametres = {parametre.code: parametre for parametre in LISTE_PARAMETRES}

    for parametre_db in PortailParametre.objects.all():
        if parametre_db.code in dict_parametres:
            dict_parametres[parametre_db.code].From_db(parametre_db.valeur)

    return {code: parametre.valeur for code, parametre in dict_parametres.items()}


def Get_parametre(code=""):
    parametres = Get_dict_parametres()
    return parametres.get(code, None)
