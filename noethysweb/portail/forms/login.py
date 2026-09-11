# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
import datetime
from django.contrib.auth.forms import AuthenticationForm
from django.forms import ValidationError
from django.utils.translation import gettext as _
from core.utils.utils_captcha import CaptchaField, CustomCaptchaTextInput
from core.models import PortailParametre
from core.constants import TYPE_COMPTE_FAMILLE

class FormLoginFamille(AuthenticationForm):
    captcha = CaptchaField(widget=CustomCaptchaTextInput)
    def __init__(self, *args, **kwargs):
        super(FormLoginFamille, self).__init__(*args, **kwargs)
        self.fields['username'].widget.attrs['class'] = "form-control"
        self.fields['username'].widget.attrs['placeholder'] = _("Identifiant")
        self.fields['password'].widget.attrs['class'] = "form-control"
        self.fields['password'].widget.attrs['placeholder'] = _("Mot de passe")
        self.fields['captcha'].widget.attrs['class'] = "form-control"
        self.fields['captcha'].widget.attrs['placeholder'] = _("Recopiez le code de sécurité ci-contre")

    def confirm_login_allowed(self, user):
        # on va chercher en base le paramètre dont le code est "type_compte"
        parametre_type_compte = PortailParametre.objects.filter(code="type_compte").first()

        # si le paramètre existe -> on prend sa valeur ("famille" ou "individu"). 
        # sinon -> on utilise TYPE_COMPTE_FAMILLE comme valeur par défaut. 
        # C'est une sécurité : si la base est vide ou nouvelle, on ne plante pas.
        type_compte = parametre_type_compte.valeur if parametre_type_compte else TYPE_COMPTE_FAMILLE
        if not user.is_active:
            raise ValidationError(_("Ce compte a été désactivé"), code='inactive')
        if user.categorie not in ["famille", "individu"]:
            raise ValidationError(_("Catégorie de compte non autorisée"), code='acces_interdit')
        if user.categorie != type_compte:
            raise ValidationError(_("Accès non autorisé"), code='acces_interdit')
        if user.date_expiration_mdp and user.date_expiration_mdp < datetime.datetime.now():
            raise ValidationError(_("Ce mot de passe a expiré"), code='mdp_expire')
