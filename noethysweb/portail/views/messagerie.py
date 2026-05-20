# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime, json
logger = logging.getLogger(__name__)
from django.urls import reverse_lazy
from django.template.defaultfilters import truncatechars, striptags
from django.utils.translation import gettext as _
from django.http import Http404
from core.views import crud
from core.models import Famille, PortailMessage, Structure, Mail, Destinataire, Rattachement
from core.utils import utils_portail
from outils.utils import utils_email
from portail.forms.messagerie import Formulaire
from portail.views.base import CustomView


class Page(CustomView):
    model = PortailMessage
    menu_code = "portail_contact"

    def get_famille_object(self):
        """Retourne la/les familles rattachées à l'utilisateur."""
        user = self.request.user
        if hasattr(user, "famille") and user.famille:
            return [user.famille]
        if hasattr(user, "individu") and user.individu:
            rattachements = Rattachement.objects.select_related("famille").filter(individu=user.individu, titulaire=1)
            familles = []
            seen_ids = set()
            for rattachement in rattachements:
                if rattachement.famille and rattachement.famille_id not in seen_ids:
                    familles.append(rattachement.famille)
                    seen_ids.add(rattachement.famille_id)
            return familles
        return []

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['page_titre'] = _("Messagerie")
        context['structure'] = Structure.objects.get(pk=self.get_idstructure())
        # récupère idfamille depuis l'URL
        idfamille = self.kwargs.get("idfamille")
        familles = self.get_famille_object()
        context["familles"] = familles
        
        # calcul messages non lus PAR FAMILLE (pour les badges)
        from django.db.models import Count
        unread_by_family = PortailMessage.objects.filter(
            famille__in=familles,
            structure_id=self.get_idstructure(),
            utilisateur__isnull=False,
            date_lecture__isnull=True,
        ).exclude(
            utilisateur=self.request.user
        ).values("famille_id").annotate(
            unread_count=Count("famille_id")
        )
        
        context["unread_messages_by_family"] = {
            item["famille_id"]: item["unread_count"] 
            for item in unread_by_family
        }

        # si une seule famille, utiliser son ID
        if not idfamille and len(familles) == 1:
            idfamille = familles[0].pk

        # sécurise l'accès à la famille demandée
        if idfamille and idfamille not in {famille.pk for famille in familles}:
            raise Http404

        # si idfamille fourni, filtrer sur cette famille
        if idfamille:
            context["discussion_famille"] = Famille.objects.get(pk=idfamille)
            context['liste_messages'] = PortailMessage.objects.select_related("famille", "utilisateur").filter(
                famille_id=idfamille,
                famille__in=familles,
                structure_id=self.get_idstructure(),
            ).order_by("date_creation")
            # messages non lus de cette discussion
            liste_messages_non_lus = context['liste_messages'].filter(
                date_lecture__isnull=True,
                utilisateur__isnull=False
            ).exclude(utilisateur=self.request.user)
            context['liste_messages_non_lus'] = list(liste_messages_non_lus)

            # marquer les messages non lus comme lus
            liste_messages_non_lus.update(date_lecture=datetime.datetime.now())
        else:
            context["discussion_famille"] = None
            context['liste_messages'] = PortailMessage.objects.none()

        return context

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["idfamille"] = self.kwargs.get("idfamille")
        form_kwargs["idstructure"] = self.get_idstructure()
        return form_kwargs

    def get_idstructure(self):
        return self.kwargs.get("idstructure", 0)

    def get_success_url(self):
        idfamille = self.kwargs.get('idfamille')
        if idfamille:
            return reverse_lazy('portail_messagerie_famille', kwargs={'idstructure': self.get_idstructure(), 'idfamille': idfamille})
        return reverse_lazy('portail_messagerie', kwargs={'idstructure': self.get_idstructure()})


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    template_name = "portail/messagerie.html"
    texte_confirmation = _("Le message a bien été envoyé")
    titre_historique = "Ajouter un message"

    def get(self, request, *args, **kwargs):
        # si une seule famille et pas d'idfamille dans l'URL, rediriger vers le chat directement
        idfamille = self.kwargs.get("idfamille")
        if not idfamille:
            familles = self.get_famille_object()
            if len(familles) == 1:
                from django.shortcuts import redirect
                return redirect(
                    'portail_messagerie_famille',
                    idstructure=self.get_idstructure(),
                    idfamille=familles[0].pk,
                )
        return super().get(request, *args, **kwargs)

    def Get_detail_historique(self, instance):
        return "Destinataire=%s Texte=%s" % (instance.structure, truncatechars(striptags(instance.texte), 40))

    def form_valid(self, form):
        message = form.save(commit=False)
        
        idstructure = self.kwargs["idstructure"]
        familles = self.get_famille_object()
        idfamille = self.kwargs.get("idfamille")
        if not idfamille and len(familles) == 1:
            idfamille = familles[0].pk
        if not idfamille or idfamille not in {famille.pk for famille in familles}:
            raise Http404

        # Garantit la présence d'idfamille pour la suite du flux (success_url, notifications, etc.)
        self.kwargs["idfamille"] = idfamille
        
        message.structure_id = idstructure
        message.famille_id = idfamille
        #message.individu_id = None  # Pas de discussion individuelle
        message.utilisateur = None  # Message envoyé par la famille
        message.date_creation = datetime.datetime.now()
        
        message.save()
        
        return super().form_valid(form)

    def Apres_form_valid(self, form=None, instance=None):
        """ Envoie une notification de nouveau message à l'administrateur par email """
        try:
            # Vérifie qu'une notification doit être envoyée
            parametres_portail = utils_portail.Get_dict_parametres()
            if not parametres_portail.get("messagerie_envoyer_notification_admin", False):
                return

            # Importation de la structure concernée
            structure = Structure.objects.get(pk=self.get_idstructure())
            if not structure.adresse_exp:
                return
            
            # Récupère la famille depuis l'URL
            idfamille = self.kwargs.get("idfamille")
            famille = Famille.objects.get(pk=idfamille)
            url_message = self.request.build_absolute_uri(reverse_lazy("messagerie_portail", kwargs={"idstructure": structure.pk, "idfamille": self.kwargs.get("idfamille")}))

            # Création du contenu du mail
            contenu_message = """
            <p>Bonjour,</p>
            <p>Vous avez reçu un nouveau message de <b>%s</b> sur le portail.</p>
            <p>Vous pouvez le consulter et y répondre en cliquant sur le lien suivant : <a href="%s" target="_blank">Accéder au message</a>.</p>
            <p>L'administrateur du portail</p>
            """ % (famille, url_message)

            # Création de l'email
            mail = Mail.objects.create(categorie="saisie_libre",
                objet="Nouveau message sur le portail",
                html=contenu_message,
                adresse_exp=structure.adresse_exp,
                utilisateur=self.request.user if self.request else None,
            )
            destinataire = Destinataire.objects.create(categorie="saisie_libre", adresse=structure.adresse_exp.adresse)
            mail.destinataires.add(destinataire)
            succes = utils_email.Envoyer_model_mail(idmail=mail.pk, request=self.request)
        except Exception as err:
            logger.error("Erreur dans l'envoi de la notification de message par email à l'amdinistrateur : %s" % err)
