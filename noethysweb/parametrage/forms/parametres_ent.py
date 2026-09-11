from django import forms
from django.utils.safestring import mark_safe
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Fieldset
from crispy_forms.bootstrap import Field, AppendedText
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.models import Organisateur


ICONE_AFFICHER_MDP = mark_safe(
    '<a id="id_afficher_ent_password" href="" title="Afficher ou masquer le mot de passe">'
    '<i id="id_eye_ent_password" class="fa fa-fw fa-eye-slash" aria-hidden="true"></i></a>'
)

EXTRA_SCRIPT = """
<script>
$(document).ready(function () {
    $('#id_afficher_ent_password').click(function (event) {
        event.preventDefault();
        $('#id_ent_password').attr('type', $('#id_ent_password').is(':password') ? 'text' : 'password');
        if ($('#id_ent_password').attr('type') === 'password') {
            $('#id_eye_ent_password').removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            $('#id_eye_ent_password').removeClass('fa-eye-slash').addClass('fa-eye');
        }
    });
});
</script>
"""


class Formulaire(FormulaireBase, forms.ModelForm):
    class Meta:
        model = Organisateur
        fields = ["ent_active", "ent_username", "ent_password"]

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
                Field("ent_username"),
                AppendedText("ent_password", ICONE_AFFICHER_MDP),
            ),
            HTML(EXTRA_SCRIPT),
        )
        self.fields["ent_password"].widget = forms.PasswordInput(render_value=True)
