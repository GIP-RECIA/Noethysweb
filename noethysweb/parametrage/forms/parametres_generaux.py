#  Copyright (c) 2024 GIP RECIA.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, Submit, HTML, Fieldset, Div, ButtonHolder
from crispy_forms.bootstrap import Field, InlineRadios
from core.utils.utils_commandes import Commandes
from core.models import PortailParametre
from core.utils.utils_parametres_generaux import LISTE_PARAMETRES


LISTE_RUBRIQUES = [
    ("Compte Utilisateurs", ["type_compte"]),

    ("Fiche Individu", ["questionnaire_afficher_page_individu" , "liens_afficher_page_individu", "regimes_alimentaires_afficher_page_individu",
             "maladies_afficher_page_individu" ,"medical_afficher_page_individu" , "assurances_afficher_page_individu" , "contacts_afficher_page_individu" ,
             "transports_afficher_page_individu" , "consommations_afficher_page_individu"]),

    ("Fiche Famille", ["questionnaire_afficher_page_famille" , "pieces_afficher_page_famille" , "locations_afficher_page_famille" ,
            "cotisations_afficher_page_famille" , "caisse_afficher_page_famille" , "aides_afficher_page_famille" , "quotients_afficher_page_famille" ,
            "prestations_afficher_page_famille" , "factures_afficher_page_famille" , "reglements_afficher_page_famille" ,
            "messagerie_afficher_page_famille" , "outils_afficher_page_famille" , "consommations_afficher_page_famille"]),

    ("Portail Utilisateur", [
        "outils_afficher_page_portailuser" ,"locations_afficher_page_portailuser" , "adhesions_afficher_page_portailuser" ,
            "consommations_afficher_page" ,"factures_afficher_page_portailuser" , "reglements_afficher_page_portailuser"
            , "comptabilite_afficher_page_portailuser" ,"collabotrateurs_afficher_page_portailuser" , "aides_afficher_page_portailuser"])

]


class Formulaire(FormulaireBase, forms.Form):
    type_compte = forms.ChoiceField(
        label="",  # Label vide pour ne pas afficher "Type de compte*"
        choices=[("famille", "Compte Famille"), ("individu", "Compte Individu")],
        widget=forms.RadioSelect(),
        initial="famille",
        help_text="Sélectionnez le type de compte à utiliser pour se connecter au portail"
    )
    
    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'compte_parametres_form'
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'

        # Initialisation du layout
        self.helper.layout = Layout()
        self.helper.layout.append(Commandes(annuler_url="{% url 'parametres_generaux' %}", ajouter=False))

        dict_parametres = {parametre.code: parametre for parametre in LISTE_PARAMETRES}
        for parametre_db in PortailParametre.objects.all():
            if parametre_db.code in dict_parametres:
                dict_parametres[parametre_db.code].From_db(parametre_db.valeur)
                
        # Initialiser le champ type_compte en fonction des valeurs actuelles
        # Rechercher si le compte individu est explicitement activé (seul cas où on le sélectionne)
        compte_individu_actif = False
        compte_famille_actif = False
        
        for parametre_db in PortailParametre.objects.filter(code__in=["compte_famille", "compte_individu"]):
            if parametre_db.code == "compte_individu" and parametre_db.valeur.lower() in ["true", "1"]:
                compte_individu_actif = True
            if parametre_db.code == "compte_famille" and parametre_db.valeur.lower() in ["true", "1"]:
                compte_famille_actif = True
        
        # Règle d'initialisation :
        # - Utiliser "individu" uniquement si c'est explicitement activé ET que famille ne l'est pas
        # - Utiliser "famille" dans tous les autres cas
        # Note: Avec les boutons radio, il ne sera plus possible d'avoir les deux options activées 
        # simultanément à l'avenir, mais ce code doit gérer les données existantes pendant la transition
        if compte_individu_actif and not compte_famille_actif:
            self.fields["type_compte"].initial = "individu"
        else:
            self.fields["type_compte"].initial = "famille"

        # Création des fields
        for titre_rubrique, liste_parametres in LISTE_RUBRIQUES:
            liste_fields = []
            for code_parametre in liste_parametres:
                # Si c'est notre champ personnalisé type_compte, il est déjà défini dans la classe
                if code_parametre == "type_compte":
                    liste_fields.append(InlineRadios(code_parametre))
                    continue
                
                # Pour les autres champs standard
                self.fields[code_parametre] = dict_parametres[code_parametre].Get_ctrl()
                self.fields[code_parametre].initial = dict_parametres[code_parametre].valeur
                liste_fields.append(Field(code_parametre))
            self.helper.layout.append(Fieldset(titre_rubrique, *liste_fields))

        self.helper.layout.append(HTML("<br>"))

    # La méthode clean() a été supprimée car elle n'est plus nécessaire
    # Les boutons radio garantissent qu'un seul choix est possible
