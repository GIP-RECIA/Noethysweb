from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Fieldset
from crispy_forms.bootstrap import Field
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.models import Organisateur


class Formulaire(FormulaireBase, forms.ModelForm):
    class Meta:
        model = Organisateur
        fields = ["ent_active", "ent_url", "ent_client_id", "ent_client_secret", "ent_username", "ent_password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = "parametres_ent_form"
        self.helper.form_method = "post"
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-md-3"
        self.helper.field_class = "col-md-9"
        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'parametrage_toc' %}", ajouter=False),
            Fieldset("Activation",
                Field("ent_active"),
            ),
            Fieldset("Connexion OAuth2",
                Field("ent_url"),
                Field("ent_client_id"),
                Field("ent_client_secret"),
                Field("ent_username"),
                Field("ent_password"),
            ),
        )
        self.fields["ent_url"].widget.attrs["placeholder"] = "https://recette-ode4.opendigitaleducation.com"
        self.fields["ent_client_secret"].widget = forms.PasswordInput(render_value=True)
        self.fields["ent_password"].widget = forms.PasswordInput(render_value=True)
