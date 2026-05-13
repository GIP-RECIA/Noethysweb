# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
logger = logging.getLogger(__name__)
from django import forms
from django.forms import ValidationError
from django.contrib.auth.password_validation import get_password_validators
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.safestring import mark_safe
from django.core.validators import validate_email
from core.models import Individu
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from crispy_forms.bootstrap import Field
from core.utils.utils_captcha import CaptchaField, CustomCaptchaTextInput


class FormCreerCompte(forms.Form):
    civilite = forms.ChoiceField(label="Civilité", choices=[(1, "Monsieur"), (3, "Madame")], required=True, help_text="Sélectionnez une civilité dans la liste déroulante.")
    nom = forms.CharField(label="Nom de famille", required=True, help_text="Saisissez votre nom de famille en majuscules. Ex : DUPOND.")
    prenom = forms.CharField(label="Prénom", required=True, help_text="Saisissez votre prénom en minuscules avec la première lettre en majuscule. Ex : Sophie.")
    email = forms.CharField(label="Email", required=True, max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}), help_text="Saisissez votre adresse email. Elle sera utilisée pour vous envoyer un email d'activation.")
    mdp1 = forms.CharField(label="Mot de passe", required=True, widget=forms.TextInput(attrs={"type": "password"}), help_text="")
    mdp2 = forms.CharField(label="Mot de passe", required=True, widget=forms.TextInput(attrs={"type": "password"}), help_text="Saisissez une seconde fois le mot de passe choisi.")
    captcha = CaptchaField(widget=CustomCaptchaTextInput)
    check_conditions = forms.BooleanField(label=mark_safe("J'accepte les <a href='#' data-toggle='modal' data-target='#modal_conditions'>conditions d'utilisation</a>"), required=True, initial=False)

    def __init__(self, *args, **kwargs):
        super(FormCreerCompte, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = "form_creer_compte"
        self.helper.form_method = "post"
        self.helper.form_tag = False
        self.helper.form_show_errors = False

        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-md-3"
        self.helper.field_class = "col-md-9"

        self.fields["captcha"].widget.attrs["placeholder"] = _("Recopiez le code de sécurité ci-contre")

        # Affichage des exigences de mot de passe dans le help_text
        exigences = ["<li>%s</li>" % v.get_help_text() for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS)]
        self.fields["mdp1"].help_text = "<ul style='padding-left: 16px;padding-bottom: 0px;margin-bottom: 0;'>%s</ul>" % "".join(exigences)

        self.helper.layout = Layout(
            Field("civilite"),
            Field("nom"),
            Field("prenom"),
            Field("email"),
            Field("mdp1"),
            Field("mdp2"),
            Field("captcha"),
            Field("check_conditions"),
        )

    def clean(self):
        # Vérifie la cohérence de l'adresse mail
        try:
            validate_email(self.cleaned_data["email"])
        except:
            raise ValidationError(_("L'adresse Email n'est pas valide"))

        # Vérifie que cette adresse mail n'est pas déjà utilisée
        for individu in Individu.objects.filter(mail__isnull=False):
            if individu.mail == self.cleaned_data["email"] :
                raise ValidationError(_("Cette adresse mail est déjà répertoriée, vous ne pouvez donc pas créer de nouveau compte. Contactez l'administrateur."))

        # Vérifie que les deux mots de passe sont identiques
        if self.cleaned_data["mdp1"] != self.cleaned_data["mdp2"]:
            raise ValidationError(_("Les deux mots de passe saisis ne sont pas identiques."))

        return self.cleaned_data
