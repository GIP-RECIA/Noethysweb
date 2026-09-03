# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json
from django import forms
from django.urls import reverse_lazy
from django.forms import ModelForm
from django.contrib import messages
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, HTML
from crispy_forms.bootstrap import Field, StrictButton
from core.models import PortailMessage, ModeleEmail, Mail, Destinataire, Rattachement
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.utils import utils_portail
from portail.utils.utils_summernote import SummernoteTextFormField
from outils.utils import utils_email


def Envoi_notification_message(request=None, famille=None, structure=None, emails_destinataires=None):
    """ Envoie une notification de nouveau message à la famille par email """
    # Vérifie qu'une notification doit être envoyée
    parametres_portail = utils_portail.Get_dict_parametres()
    if not parametres_portail.get("messagerie_envoyer_notification_famille", False):
        return False

    # Recherche le modèle d'email
    modele_email = ModeleEmail.objects.filter(categorie="portail_notification_message", defaut=True).first()
    if not modele_email:
        messages.add_message(request, messages.ERROR, "Envoi de la notification par email impossible : Aucun modèle d'email n'a été paramétré")
        return False

    # Création de l'email
    mail = Mail.objects.create(
        categorie="portail_notification_message",
        objet=modele_email.objet if modele_email else "",
        html=modele_email.html if modele_email else "",
        adresse_exp=structure.adresse_exp,
        selection="NON_ENVOYE",
        utilisateur=request.user if request else None,
    )
    url_message = request.build_absolute_uri(reverse_lazy("portail_messagerie", kwargs={'idstructure': structure.pk}))
    valeurs_fusion = {"{URL_MESSAGE}": "<a href='%s'>Accéder au message</a>" % url_message}

    # déterminer les emails destinataires
    if emails_destinataires:
        liste_emails = [e for e in emails_destinataires if e]
    else:
        liste_emails = [famille.mail] if famille.mail else []

    if not liste_emails:
        messages.add_message(request, messages.ERROR, "La notification par email n'a pas pu être envoyée : aucun email destinataire trouvé")
        return False

    for email in liste_emails:
        destinataire = Destinataire.objects.create(
            categorie="famille", famille=famille, adresse=email, valeurs=json.dumps(valeurs_fusion)
        )
        mail.destinataires.add(destinataire)

    succes = utils_email.Envoyer_model_mail(idmail=mail.pk, request=request)
    if succes:
        messages.add_message(request, messages.INFO, "Une notification a été envoyé par email à la famille")
    else:
        messages.add_message(request, messages.ERROR, "La notification par email n'a pas pu être envoyée à la famille")
    return True


class Formulaire(FormulaireBase, ModelForm):
    texte = SummernoteTextFormField(label="Poster un message", attrs={'summernote': {'width': '100%', 'height': '200px', 'toolbar': [
        ['font', ['bold', 'underline', 'clear']],
        ['color', ['color']],
        ['para', ['ul', 'ol', 'paragraph']],
        ['insert', ['link', 'picture']],
        ['view', ['codeview', 'help']],
        ]}})

    emails_destinataires = forms.MultipleChoiceField(
        label="Notifier par email",
        widget=forms.CheckboxSelectMultiple,
        required=False,
        choices=[],
    )

    class Meta:
        model = PortailMessage
        fields = ("famille", "structure", "utilisateur", "texte")

    def __init__(self, *args, **kwargs):
        idfamille = kwargs.pop("idfamille", None)
        idstructure = kwargs.pop("idstructure", None)
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'portail_messages_form'
        self.helper.form_method = 'post'

        # construire les choix d'emails depuis les titulaires de la famille
        choices = []
        if idfamille:
            rattachements = Rattachement.objects.filter(
                famille_id=idfamille, titulaire=True
            ).select_related('individu')
            choices = [
                (r.individu.mail, "%s (%s)" % (r.individu.Get_nom(), r.individu.mail))
                for r in rattachements if r.individu.mail
            ]
        self.fields['emails_destinataires'].choices = choices
        self.initial['emails_destinataires'] = [c[0] for c in choices]

        # Affichage
        layout_fields = [
            Hidden('famille', value=idfamille),
            Hidden('structure', value=idstructure),
            Hidden('utilisateur', value=self.request.user.pk),
            Field('texte'),
        ]
        if choices:
            layout_fields.append(Field('emails_destinataires'))
        layout_fields.append(
            Commandes(enregistrer_label="<i class='fa fa-send margin-r-5'></i>Envoyer", annuler_url="{% url 'portail_contact' %}", ajouter=False, aide=False, css_class="pull-right")
        )
        self.helper.layout = Layout(*layout_fields)
