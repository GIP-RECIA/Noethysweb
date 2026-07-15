# -*- coding: utf-8 -*-

from datetime import date

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.db import transaction
from core.models import Individu, Scolarite
from core.views.base import CustomView
from core.utils.utils_ent import get_user
from fiche_individu.views.individu import Onglet


CHAMPS_SYNC = [
    {"code": "nom",        "label": "Nom",              "ent_key": "lastName"},
    {"code": "prenom",     "label": "Prénom",           "ent_key": "firstName"},
    {"code": "mail",       "label": "Email",            "ent_key": "email"},
    {"code": "tel_mobile", "label": "Téléphone mobile", "ent_key": "mobile"},
    {"code": "rue_resid",  "label": "Adresse",          "ent_key": "address"},
    {"code": "cp_resid",   "label": "Code postal",      "ent_key": "zipCode"},
    {"code": "ville_resid","label": "Ville",            "ent_key": "city"},
]


def Get_scolarite_actuelle(individu):
    """ Retourne la scolarité de l'individu dont la période couvre aujourd'hui, sinon la plus récente. """
    aujourdhui = date.today()
    scolarite = Scolarite.objects.filter(individu=individu, date_debut__lte=aujourdhui, date_fin__gte=aujourdhui).first()
    if not scolarite:
        scolarite = Scolarite.objects.filter(individu=individu).order_by("-date_debut").first()
    return scolarite


def Est_profil_eleve(data_ent):
    """
    Vérifie que les données ENT correspondent à un profil élève. L'ENT renvoie aussi un champ
    "structures" pour les parents (rattachement administratif au portail de l'école), qu'il ne
    faut pas confondre avec une vraie scolarité - seuls les élèves ont une classe.
    """
    type_profil = data_ent.get("type") or data_ent.get("profiles") or []
    if isinstance(type_profil, str):
        type_profil = [type_profil]
    return "Student" in type_profil


def Get_lignes_comparaison(individu, data_ent):
    """ Retourne la liste des champs comparés entre Noethysweb et l'ENT pour un individu. """
    # Import ici pour éviter un import circulaire au chargement du module
    from fiche_famille.views.famille_ent import _normaliser_enfant

    lignes = []
    for champ in CHAMPS_SYNC:
        val_noethys = getattr(individu, champ["code"]) or ""
        val_ent = data_ent.get(champ["ent_key"]) or ""
        lignes.append({
            "code": champ["code"],
            "label": champ["label"],
            "val_noethys": val_noethys,
            "val_ent": val_ent,
            "different": str(val_noethys).strip() != str(val_ent).strip(),
        })

    # Ecole / classe : cas particulier, ce n'est pas un champ direct sur l'individu mais une
    # relation via Scolarité - on ne propose la comparaison que pour un élève (pas un parent,
    # qui a lui aussi un champ "structures" côté ENT sans que ça soit une scolarité).
    data_ent_norm = _normaliser_enfant(dict(data_ent))
    ecole_ent = data_ent_norm.get("ecole_nom") or ""
    if ecole_ent and Est_profil_eleve(data_ent):
        classe_ent = data_ent_norm.get("classe_nom") or ""
        scolarite_actuelle = Get_scolarite_actuelle(individu)
        ecole_noethys = scolarite_actuelle.ecole.nom if scolarite_actuelle and scolarite_actuelle.ecole else ""
        classe_noethys = scolarite_actuelle.classe.nom if scolarite_actuelle and scolarite_actuelle.classe else ""
        lignes.append({
            "code": "ecole_classe",
            "label": "École / Classe",
            "val_noethys": f"{ecole_noethys} - {classe_noethys}" if classe_noethys else ecole_noethys,
            "val_ent": f"{ecole_ent} - {classe_ent}" if classe_ent else ecole_ent,
            "different": ecole_noethys.strip() != ecole_ent.strip() or classe_noethys.strip() != classe_ent.strip(),
        })

    return lignes


def Appliquer_sync_ecole_classe(individu, data_ent):
    """
    Met à jour la scolarité actuelle de l'individu avec l'école/classe de l'ENT (ou en crée
    une s'il n'en a aucune). Ne garde pas d'historique des changements côté Noethys - l'ENT/
    l'Éducation Nationale garde déjà cet historique de son côté (champ "oldClasses").
    """
    from fiche_famille.views.famille_ent import _normaliser_enfant, _get_ou_creer_ecole, _get_ou_creer_classe, _creer_scolarite

    if not Est_profil_eleve(data_ent):
        return False

    data_ent = _normaliser_enfant(dict(data_ent))
    if not data_ent.get("ecole_nom"):
        return False

    scolarite = Get_scolarite_actuelle(individu)
    if scolarite:
        scolarite.ecole = _get_ou_creer_ecole(data_ent.get("ecole_nom"), data_ent.get("ecole_uai"))
        scolarite.classe = _get_ou_creer_classe(
            scolarite.ecole, data_ent.get("classe_nom"),
            data_ent.get("startDateClasses"), data_ent.get("endDateClasses"),
        )
        scolarite.save()
    else:
        _creer_scolarite(individu, data_ent)
    return True


class SynchroniserIndividu(Onglet, TemplateView):
    menu_code = "individus_toc"
    template_name = "fiche_individu/individu_ent_synchro.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box_titre'] = "Synchronisation ENT"
        context['onglet_actif'] = "resume"

        individu = context['individu']

        if not individu.ent_id:
            context['erreur'] = "Cet individu n'a pas été importé depuis l'ENT."
            return context

        data_ent = get_user(individu.ent_id)
        if not data_ent:
            context['erreur'] = "Impossible de récupérer les données depuis l'ENT. Vérifiez la connexion."
            return context

        context['lignes'] = Get_lignes_comparaison(individu, data_ent)
        return context

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        idfamille = self.kwargs['idfamille']
        idindividu = self.kwargs['idindividu']
        individu = Individu.objects.get(pk=idindividu)

        data_ent = get_user(individu.ent_id)
        if not data_ent:
            messages.error(request, "Impossible de récupérer les données ENT.")
            return redirect(reverse('individu_ent_synchro', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))

        champs_selectionnes = request.POST.getlist('champs')
        nb_modifs = 0

        for champ in CHAMPS_SYNC:
            if champ["code"] in champs_selectionnes:
                val_ent = data_ent.get(champ["ent_key"]) or ""
                setattr(individu, champ["code"], val_ent or None)
                nb_modifs += 1

        if "ecole_classe" in champs_selectionnes:
            if Appliquer_sync_ecole_classe(individu, data_ent):
                nb_modifs += 1

        if nb_modifs:
            individu.save()
            messages.success(request, f"{nb_modifs} champ(s) synchronisé(s) depuis l'ENT.")
        else:
            messages.info(request, "Aucun champ sélectionné.")

        return redirect(reverse('individu_ent_synchro', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))
