from django import forms
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Div
from crispy_forms.bootstrap import Field
from core.utils.utils_commandes import Commandes
from django.core.cache import cache
from core.models import Organisateur


class Formulaire(FormulaireBase, forms.Form):
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
        self.helper.layout.append(Commandes(annuler_url="{% url 'parametres_ent' %}", ajouter=False))
        organisateur = Organisateur.objects.filter(pk=1).first()
        # === Création des fields ===
        self.fields["sans_ent"] = forms.BooleanField(
            label="Sans ENT",
            required=False,
            widget=forms.CheckboxInput(attrs={'class': 'text-start'})
        )
        self.fields["sans_ent"].initial = False

        self.fields["activer_ent"] = forms.BooleanField(
            label="ENT", 
            required=False,
            widget=forms.CheckboxInput(attrs={'class': 'text-start'})
        )
        self.fields["activer_ent"].initial = True
        self.fields["activer_ent"].initial = organisateur.ent_active
        self.fields["sans_ent"].initial = not organisateur.ent_active
        # === CSS personnalisé pour les checkboxes ===
        custom_css = """
        <style>
            .custom-checkbox {
                text-align: left !important;
                padding-left: 15px !important;
                margin-left: 0 !important;
                display: flex;
                align-items: center;
                justify-content: flex-start;
            }
            .custom-checkbox label {
                font-weight: 500 !important;
                font-size: 16px !important;
                color: #333 !important;
                margin-left: 5px;
                margin-bottom: 0 !important;
            }
            .custom-checkbox input[type="checkbox"] {
                margin-right: 10px;
                transform: scale(1.2);
                margin-top: 0 !important;
            }
            .custom-help-text {
                margin-left: 40px;
                margin-top: 0px;
                margin-bottom: 15px;
                color: #666;
                font-size: 13px;
                font-style: italic;
            }
            .checkbox-container {
                padding-left: 15px;
            }
        </style>
        """
        self.helper.layout.append(HTML(custom_css))

        # === Placement Sans ENT en premier ===
        self.helper.layout.append(
            Div(
                Div("sans_ent", css_class="custom-checkbox"),
                css_class="checkbox-container"
            )
        )
        self.helper.layout.append(
            Div(
                HTML('<div class="custom-help-text">Cochez cette case pour Désactiver l\'intégration avec l\'Espace Numérique de Travail</div>'),
                css_class="text-start"
            )
        )

        # === Ensuite ENT ===
        self.helper.layout.append(
            Div(
                Div("activer_ent", css_class="custom-checkbox"),
                css_class="checkbox-container"
            )
        )
        self.helper.layout.append(
            Div(
                HTML('<div class="custom-help-text">Cochez cette case pour activer l\'intégration avec l\'Espace Numérique de Travail</div>'),
                css_class="text-start"
            )
        )

        self.helper.layout.append(HTML("<br>"))
        self.helper.layout.append(HTML(EXTRA_SCRIPT))

    def clean(self):
        cleaned_data = super().clean()
        activer_ent = cleaned_data.get('activer_ent')
        sans_ent = cleaned_data.get('sans_ent')
        organisateur = cache.get('organisateur', None)
        if not organisateur:
            organisateur = cache.get_or_set('organisateur', Organisateur.objects.filter(pk=1).first())
        organisateur.ent_active = activer_ent
        organisateur.save()
        print("*/*/*/*/")
        print(activer_ent)
        if not activer_ent and not sans_ent:
            raise forms.ValidationError(
                "Vous devez cocher au moins une option : ENT ou Sans ENT."
            )
        return cleaned_data
    
# Mise à jour du EXTRA_SCRIPT pour gérer les 2 checkboxes
EXTRA_SCRIPT = """
<script>
window.onload = function() {
    const checkboxEnt = document.getElementById("id_activer_ent");
    const checkboxSansEnt = document.getElementById("id_sans_ent");

    console.log("Checkboxes ENT et Sans ENT trouvées avec succès");

    if (checkboxEnt && checkboxSansEnt) {
        checkboxEnt.addEventListener('change', function() {
            if (this.checked) {
                checkboxSansEnt.checked = false;
                checkboxSansEnt.disabled = true;
            } else {
                checkboxSansEnt.disabled = false;
            }
        });

        checkboxSansEnt.addEventListener('change', function() {
            if (this.checked) {
                checkboxEnt.checked = false;
                checkboxEnt.disabled = true;
            } else {
                checkboxEnt.disabled = false;
            }
        });
    }
};
</script>
<br>
"""
