# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, ButtonHolder
from crispy_forms.bootstrap import Field, StrictButton
from portail.forms.fiche import FormulaireBase
from portail.widgets import ValidationApprobation
from portail.utils import utils_approbations


class Formulaire(FormulaireBase, forms.Form):
    def __init__(self, *args, **kwargs):
        self.famille = kwargs.pop('famille', None) or kwargs.pop('instance', None)
        familles = kwargs.pop('familles', None)
        self.mode = kwargs.pop("mode", "CONSULTATION")
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'famille_approbations_form'
        self.helper.form_method = 'post'
        self.helper.form_show_labels = False
        self.helper.form_tag = False
        self.helper.layout = Layout()

        # Résolution de la liste de familles
        if not familles:
            famille = self.famille
            if not famille and self.request and hasattr(self.request.user, "famille"):
                famille = self.request.user.famille
            familles = [famille] if famille else []

        for famille in familles:
            approbations_requises = utils_approbations.Get_approbations_requises(famille=famille)

            # Consentements — clé encode la famille pour le form_valid
            for unite_consentement in approbations_requises["consentements"]:
                ctrl = forms.BooleanField(widget=ValidationApprobation(attrs={"unite_consentement": unite_consentement}), required=False)
                code = "unite_%d_%d" % (famille.pk, unite_consentement.pk)
                self.fields[code] = ctrl
                self.helper.layout.append(Field(code))

            # Certifications des fiches individuelles
            for rattachement in approbations_requises["rattachements"]:
                ctrl = forms.BooleanField(widget=ValidationApprobation(attrs={"rattachement": rattachement}), required=False)
                code = "rattachement_%d" % rattachement.pk
                self.fields[code] = ctrl
                self.helper.layout.append(Field(code))

            # Certification de la fiche famille
            for fam in approbations_requises["familles"]:
                ctrl = forms.BooleanField(widget=ValidationApprobation(attrs={"famille": fam}), required=False)
                code = "famille_%d" % fam.pk
                self.fields[code] = ctrl
                self.helper.layout.append(Field(code))

        # Création des contrôles de validation
        if not self.fields:
            self.helper.layout.append(HTML("<strong>Aucune approbation n'est actuellement nécessaire.</strong>"))
