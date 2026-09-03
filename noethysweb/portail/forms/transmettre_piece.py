# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime
from django import forms
from django.forms import ModelForm
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, HTML
from crispy_forms.bootstrap import Field
from core.models import Piece, Rattachement, Individu
from core.utils.utils_commandes import Commandes
from portail.forms.fiche import FormulaireBase
from individus.utils import utils_pieces_manquantes
from core.models import Famille


class Formulaire(FormulaireBase, ModelForm):
    # Type de pièce
    selection_piece = forms.TypedChoiceField(label=_("Type de document"), choices=[], required=True, help_text=_(
        "Sélectionnez un type de document dans la liste. Sélectionnez 'Autre type' s'il ne s'agit pas d'un document prédéfini."))
    individu = forms.TypedChoiceField(label=_("Individu concerné"), choices=[], required=False, help_text=_(
        "Sélectionnez le nom de l'individu concerné ou la famille s'il s'agit d'un document qui concerne toute la famille."))
    document = forms.FileField(label=_("Document"),
                               help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png)."), required=True,
                               validators=[FileExtensionValidator(allowed_extensions=['pdf', 'png', 'jpg'])])
    famille = forms.ModelChoiceField(
        queryset=Famille.objects.all(),  # Initialement vide
        label=_("Famille concernée"),
        required=True,
        help_text=_("Sélectionnez la famille concernée par le document.")
    )

    class Meta:
        model = Piece
        fields = "__all__"
        widgets = {
            "observations": forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            "titre": _("Titre du document*"),
            "observations": _("Observations"),
        }
        help_texts = {
            "titre": _("Saisissez un titre pour ce document. Ex : Certificat médical de Sophie..."),
            "observations": _("Vous pouvez ajouter des observations si vous le souhaitez."),
        }

    def get_rattachements_for_user(self):
        rattachements = set()  # Set pour éviter les doublons
        # Vérifiez si l'utilisateur fait partie d'une famille ou d'un individu
        if hasattr(self.request.user, 'individu'):
            # Si l'utilisateur est un individu, obtenez toutes les familles auxquelles il est rattaché
            rattachements_query = Rattachement.objects.filter(individu=self.request.user.individu)
            rattachements.update(rattachements_query)

        elif hasattr(self.request.user, 'famille'):
            # Si l'utilisateur fait partie d'une famille, obtenir les pièces jointes pour cette famille
            rattachements_query = Rattachement.objects.filter(famille=self.request.user.famille)
            rattachements.update(rattachements_query)
        return list(rattachements)  # Reconvertir en liste

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'portail_transmettre_piece_form'
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2 col-form-label'
        self.helper.field_class = 'col-md-10'
        self.helper.use_custom_control = False

        # Détermination des familles accessibles
        familles = []
        user = self.request.user
        if hasattr(user, 'famille') and user.famille:
            familles = [user.famille]
        elif hasattr(user, 'individu') and user.individu:
            rattachements_familles = Rattachement.objects.select_related("famille").filter(individu=user.individu, titulaire=1)
            seen_ids = set()
            for rattachement in rattachements_familles:
                if rattachement.famille and rattachement.famille_id not in seen_ids:
                    familles.append(rattachement.famille)
                    seen_ids.add(rattachement.famille_id)

        # Dropdown familles
        self.fields["famille"].queryset = Famille.objects.filter(pk__in=[famille.pk for famille in familles])
        self.fields["famille"].empty_label = "------------" if len(familles) > 1 else None

        # Famille sélectionnée (GET/POST)
        selected_famille = familles[0] if familles else None
        if self.is_bound:
            famille_id = self.data.get("famille")
            if famille_id:
                try:
                    selected_famille = self.fields["famille"].queryset.get(pk=int(famille_id))
                except (ValueError, Famille.DoesNotExist):
                    pass
        if selected_famille:
            self.fields["famille"].initial = selected_famille

        # Pièces à fournir (selon famille sélectionnée)
        self.liste_pieces_fournir = []
        if selected_famille:
            self.liste_pieces_fournir = utils_pieces_manquantes.Get_pieces_manquantes(
                famille=selected_famille,
                exclure_individus=selected_famille.individus_masques.all(),
            )
        self.fields['selection_piece'].choices = [(index, piece["label"]) for index, piece in enumerate(self.liste_pieces_fournir)] + [(9999, "Un autre type de pièce")]
        self.fields['selection_piece'].initial = None

        # Auteur
        if not self.instance.pk:
            self.fields["auteur"].initial = self.request.user

        # Individus (selon famille sélectionnée)
        rattachements_individus = []
        if selected_famille:
            rattachements_individus = Rattachement.objects.select_related("individu").filter(
                famille=selected_famille,
            ).exclude(
                individu__in=selected_famille.individus_masques.all(),
            ).order_by("categorie")
        self.fields['individu'].choices = [(None, "La famille")] + [(rattachement.individu_id, rattachement.individu.Get_nom()) for rattachement in rattachements_individus]

        # Affichage
        self.helper.layout = Layout(
            Field("auteur", type="hidden"),
            Field('selection_piece'),
            Field('titre'),
            Field('famille'),
            Field('individu'),
            Field('document'),
            Field('observations'),
            HTML(EXTRA_SCRIPT),
            Commandes(enregistrer_label="<i class='fa fa-send margin-r-5'></i>%s" % _("Envoyer"),
                      annuler_url="{% url 'portail_documents' %}", ajouter=False, aide=False,
                      css_class="pull-right"),
        )

    def clean(self):
        # Type de pièce
        if int(self.cleaned_data["selection_piece"]) == 9999:
            if self.cleaned_data["titre"] in ("", None):
                self.add_error('titre', "Vous devez saisir un titre pour cette pièce !")
            piece = None
        else:
            piece = self.liste_pieces_fournir[int(self.cleaned_data["selection_piece"])]

        self.cleaned_data["type_piece"] = piece["type_piece"] if piece else None

        # Individu
        if piece:
            # Si pièce prédéfinie
            self.cleaned_data["individu"] = None if piece["type_piece"].public == "famille" else piece["individu"]
        else:
            # Si pièce libre
            self.cleaned_data["individu"] = Individu.objects.get(pk=self.cleaned_data["individu"]) if self.cleaned_data[
                "individu"] else None

        # Famille
        if piece and piece["type_piece"].public == "individu" and piece["type_piece"].valide_rattachement:
            self.cleaned_data["famille"] = None

        # Durée de validité
        self.cleaned_data["date_debut"] = datetime.date.today()
        self.cleaned_data["date_fin"] = piece["type_piece"].Get_date_fin_validite() if piece else datetime.date(2999, 1, 1)

        return self.cleaned_data


EXTRA_SCRIPT = """
<script>

// Sélection pièce
function On_change_selection_piece(event) {
    $('#div_id_titre').hide();
    $('#div_id_individu').hide();
    if (this.value == 9999) {
        $('#div_id_titre').show();
        $('#div_id_individu').show();
    };
}
$(document).ready(function() {
    $('#id_selection_piece').change(On_change_selection_piece);
    On_change_selection_piece.call($('#id_selection_piece').get(0));

    // Changement de la famille pour actualiser les individus
    $('#id_famille').change(function() {
        var selectedFamille = $(this).val();

        $.ajax({
            type: "POST",
            url: "{% url 'portail_ajax_inscrire_get_individus_by_famille' %}",  // Récupérer les individus dynamiquement
            data: {
                'famille': selectedFamille,
                'csrfmiddlewaretoken': '{{ csrf_token }}'
            },
            success: function(data) {
                $('#id_individu').html('<option value="">La famille</option>' + data);  // Met à jour la liste des individus
            },
            error: function(xhr, status, error) {
                console.log("Erreur lors de la récupération des individus :", error);
            }
        });

        // Changement de la famille pour actualiser les pièces manquantes
        $.ajax({
            type: "POST",
            url: "{% url 'portail_ajax_transmettre_piece_get_pieces_by_famille' %}",
            data: {
                'famille': selectedFamille,
                'csrfmiddlewaretoken': '{{ csrf_token }}'
            },
            success: function(data) {
                $('#id_selection_piece').html(data);
                On_change_selection_piece.call($('#id_selection_piece').get(0));
            },
            error: function(xhr, status, error) {
                console.log("Erreur lors de la récupération des pièces :", error);
            }
        });
    });
});

</script>
"""
