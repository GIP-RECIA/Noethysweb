# -*- coding: utf-8 -*-
#  Copyright (c) 2024-2025 Faouzia TEKAYA.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from core.constants import TYPE_COMPTE_FAMILLE, TYPE_COMPTE_INDIVIDU
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

    # Compte utilisateurs
    Parametre(code="type_compte", label="Type de compte", valeur=TYPE_COMPTE_FAMILLE, type="choice",
               choix=[(TYPE_COMPTE_FAMILLE, "Compte Famille"), (TYPE_COMPTE_INDIVIDU, "Compte Individu")],
               help_text="Sélectionnez 'Compte Famille' pour permettre aux familles de se connecter et gérer leurs membres ou 'Compte Individu' pour permettre aux utilisateurs de se connecter en tant que personne individuelle."),
               
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
