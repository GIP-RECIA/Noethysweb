from django import forms
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Div
from crispy_forms.bootstrap import Field
from core.utils.utils_commandes import Commandes
from django.core.cache import cache
from core.models import Organisateur


class FormulaireEmailExpedition(FormulaireBase, forms.Form):
    def __init__(self, *args, **kwargs):
        super(FormulaireEmailExpedition, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'compte_parametres_form'
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'

        # Initialisation du layout
        self.helper.layout = Layout()
        self.helper.layout.append(Commandes(annuler_url="{% url 'parametres_mail_expedition' %}", ajouter=False))
        organisateur = Organisateur.objects.filter(pk=1).first()
        # === Création des fields ===
        self.fields["sans_expedition"] = forms.BooleanField(
            label="Sans expedition d'emails",
            required=False,
            widget=forms.CheckboxInput(attrs={'class': 'text-start'})
        )
        self.fields["sans_expedition"].initial = False

        self.fields["activer_expedition"] = forms.BooleanField(
            label="Expédition d'emailss", 
            required=False,
            widget=forms.CheckboxInput(attrs={'class': 'text-start'})
        )
        self.fields["activer_expedition"].initial = True
        self.fields["activer_expedition"].initial = organisateur.expedition_mail_active
        self.fields["sans_expedition"].initial = not organisateur.expedition_mail_active
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

        # === Placement Sans Expédition en premier ===
        self.helper.layout.append(
            Div(
                Div("sans_expedition", css_class="custom-checkbox"),
                css_class="checkbox-container"
            )
        )
        self.helper.layout.append(
            Div(
                HTML('<div class="custom-help-text">Cochez cette case pour Désactiver l\'intégration avec l\'Espace Numérique de Travail</div>'),
                css_class="text-start"
            )
        )

        # === Ensuite Expédition ===
        self.helper.layout.append(
            Div(
                Div("activer_expedition", css_class="custom-checkbox"),
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
        activer_expedition = cleaned_data.get('activer_expedition')
        sans_expedition = cleaned_data.get('sans_expedition')
        organisateur = cache.get('organisateur', None)
        if not organisateur:
            organisateur = cache.get_or_set('organisateur', Organisateur.objects.filter(pk=1).first())
        organisateur.expedition_mail_active = activer_expedition
        organisateur.save()
        print("*/*/*/*/")
        print(activer_expedition)
        if not activer_expedition and not sans_expedition:
            raise forms.ValidationError(
                "Vous devez cocher au moins une option : Expedition ou Sans Expedition."
            )
        return cleaned_data
    
# Mise à jour du EXTRA_SCRIPT pour gérer les 2 checkboxes
EXTRA_SCRIPT = """
<script>
window.onload = function() {
    const checkboxExpedition = document.getElementById("id_activer_expedition");
    const checkboxSansExpedition = document.getElementById("id_sans_expedition");

    console.log("Checkboxes Expedition et Sans Expedition trouvées avec succès");

    if (checkboxExpedition && checkboxSansExpedition) {
        checkboxExpedition.addEventListener('change', function() {
            if (this.checked) {
                checkboxSansExpedition.checked = false;
                checkboxSansExpedition.disabled = true;
            } else {
                checkboxSansExpedition.disabled = false;
            }
        });

        checkboxSansExpedition.addEventListener('change', function() {
            if (this.checked) {
                checkboxExpedition.checked = false;
                checkboxExpedition.disabled = true;
            } else {
                checkboxExpedition.disabled = false;
            }
        });
    }
};
</script>
<br>
"""
