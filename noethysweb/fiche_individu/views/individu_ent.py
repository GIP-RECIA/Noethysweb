# -*- coding: utf-8 -*-

from datetime import date

from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.db import transaction
from core.models import Individu, Scolarite, Rattachement
from core.views.base import CustomView
from core.utils.utils_ent import get_user, get_headers, search_by_name
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
    from fiche_famille.views.famille_ent import _normaliser_enfant, _trouver_ecole

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

        # L'école actuelle de l'ENT n'est peut-être pas (encore) connue de Noethys - dans ce cas
        # on ne doit pas proposer de synchroniser cette ligne (voir _trouver_ecole : on ne crée
        # jamais d'école automatiquement).
        ecole_connue = _trouver_ecole(ecole_ent, data_ent_norm.get("ecole_uai"), data_ent_norm.get("ecole_ent_id"))

        lignes.append({
            "code": "ecole_classe",
            "label": "École / Classe",
            "val_noethys": f"{ecole_noethys} - {classe_noethys}" if classe_noethys else ecole_noethys,
            "val_ent": f"{ecole_ent} - {classe_ent}" if classe_ent else ecole_ent,
            "different": ecole_noethys.strip() != ecole_ent.strip() or classe_noethys.strip() != classe_ent.strip(),
            "ecole_non_reconnue": ecole_connue is None,
        })

    return lignes


def Appliquer_sync_ecole_classe(individu, data_ent):
    """
    Met à jour la scolarité actuelle de l'individu avec l'école/classe de l'ENT (ou en crée
    une s'il n'en a aucune). Ne garde pas d'historique des changements côté Noethys - l'ENT/
    l'Éducation Nationale garde déjà cet historique de son côté (champ "oldClasses").
    """
    from fiche_famille.views.famille_ent import _normaliser_enfant, _trouver_ecole, _get_ou_creer_classe, _creer_scolarite

    if not Est_profil_eleve(data_ent):
        return False

    data_ent = _normaliser_enfant(dict(data_ent))
    if not data_ent.get("ecole_nom"):
        return False

    ecole = _trouver_ecole(data_ent.get("ecole_nom"), data_ent.get("ecole_uai"), data_ent.get("ecole_ent_id"))
    if not ecole:
        # École ENT pas encore connue de Noethys - on ne modifie rien plutôt que d'en créer une
        # à la volée (décision d'équipe, voir _trouver_ecole).
        return False

    scolarite = Get_scolarite_actuelle(individu)
    if scolarite:
        scolarite.ecole = ecole
        scolarite.classe = _get_ou_creer_classe(
            ecole, data_ent.get("classe_nom"),
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


class LierCompteEnt(Onglet, TemplateView):
    """
    Permet de lier un individu déjà présent dans Noethys (saisi à la main, sans ent_id) à son
    compte ENT correspondant - sans créer de doublon. Une fois lié, l'individu est reconnu par
    l'import en masse (détection de fratrie) et par la synchronisation, comme s'il avait été
    importé depuis le début.
    """
    menu_code = "individus_toc"
    template_name = "fiche_individu/individu_ent_lier.html"

    def _rechercher(self, nom, prenom, idfamille, idindividu_exclu):
        """ Retourne (resultats, erreur) - un seul des deux est renseigné. """
        if not nom or not prenom:
            return None, "Veuillez saisir le prénom ET le nom."
        if get_headers() is None:
            return None, "Impossible de se connecter à l'ENT. Vérifiez que la connexion est active et que les identifiants sont corrects, ou réessayez dans quelques instants (le service ENT peut être temporairement indisponible)."
        resultats = search_by_name(last_name=nom, first_name=prenom)
        if not resultats:
            return None, f"Aucun résultat pour « {prenom} {nom} » dans l'ENT. Cet individu n'y existe peut-être pas, ou son nom y est orthographié différemment - vous pouvez essayer une autre recherche ci-dessous."

        # Import ici pour éviter un import circulaire au chargement du module
        from fiche_famille.views.famille_ent import _normaliser_texte

        # Pour chaque résultat, regarde si les membres de sa famille (donnés par l'ENT)
        # correspondent à des individus déjà présents dans cette même famille sur Noethys - pour
        # rassurer l'agent que c'est bien la bonne famille, et lui permettre de les lier en même
        # temps. Selon le profil trouvé : pour un élève on regarde ses parents, pour un parent on
        # regarde ses enfants (un adulte n'a jamais de "parents" côté ENT - sans cette symétrie,
        # chercher un parent directement n'aurait aucune corroboration possible).
        membres_famille = list(Rattachement.objects.filter(famille_id=idfamille).exclude(individu_id=idindividu_exclu).select_related('individu'))
        for resultat in resultats:
            if Est_profil_eleve(resultat):
                membres_ent = resultat.get('parents', [])
                resultat['membres_label'] = "Parents"
            else:
                membres_ent = resultat.get('children', [])
                resultat['membres_label'] = "Enfants"
            membres_enrichis = []
            for membre_ent in membres_ent:
                match = None
                for ratt in membres_famille:
                    if (_normaliser_texte(ratt.individu.nom) == _normaliser_texte(membre_ent.get('lastName') or '')
                            and _normaliser_texte(ratt.individu.prenom or '') == _normaliser_texte(membre_ent.get('firstName') or '')):
                        match = ratt.individu
                        break
                # Important : on compare à l'id précis de CE candidat, pas juste "a-t-il un
                # ent_id" - sinon un individu déjà lié à un tout autre compte ENT (erreur
                # passée) afficherait à tort "déjà lié" comme si tout était en ordre.
                membres_enrichis.append({
                    "ent": membre_ent,
                    "individu_correspondant": match,
                    "deja_lie": bool(match and match.ent_id == membre_ent.get('id')),
                    "lie_a_autre_compte": bool(match and match.ent_id and match.ent_id != membre_ent.get('id')),
                })
            resultat['membres_enrichis'] = membres_enrichis
        return resultats, None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['box_titre'] = "Lier à un compte ENT"
        return context

    def get(self, request, *args, **kwargs):
        idfamille = self.kwargs['idfamille']
        idindividu = self.kwargs['idindividu']
        context = self.get_context_data()
        individu = context['individu']

        # Recherche automatique avec le nom déjà connu dans Noethys, pour éviter à l'agent
        # de le retaper - le formulaire ci-dessous reste modifiable en cas d'échec (accent,
        # orthographe différente, nom de naissance...).
        context['nom_recherche'] = individu.nom
        context['prenom_recherche'] = individu.prenom or ""
        context['resultats'], context['erreur'] = self._rechercher(individu.nom, individu.prenom, idfamille, idindividu)
        context['recherche_auto'] = True
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        idfamille = self.kwargs['idfamille']
        idindividu = self.kwargs['idindividu']
        action = request.POST.get('action', 'rechercher')

        if action == 'rechercher':
            nom = request.POST.get('nom', '').strip()
            prenom = request.POST.get('prenom', '').strip()
            resultats, erreur = self._rechercher(nom, prenom, idfamille, idindividu)

            context = self.get_context_data()
            context['nom_recherche'] = nom
            context['prenom_recherche'] = prenom
            context['resultats'] = resultats
            context['erreur'] = erreur
            context['recherche_auto'] = False
            return self.render_to_response(context)

        elif action == 'lier':
            ent_id = request.POST.get('ent_id')
            if not ent_id:
                messages.error(request, "Donnée manquante.")
            elif Individu.objects.filter(ent_id=ent_id).exists():
                messages.error(request, "Ce compte ENT est déjà lié à un autre individu dans Noethys.")
            else:
                individu = Individu.objects.get(pk=idindividu)
                individu.ent_id = ent_id
                individu.save()
                nb_lies = 1
                echecs = {}  # {idindividu (str): raison}

                # Lie aussi les parents cochés (correspondances trouvées dans la même famille)
                for cle, valeur in request.POST.items():
                    if cle.startswith('parent_lier_') and valeur:
                        autre_id = cle.replace('parent_lier_', '')
                        autre_individu = Individu.objects.filter(pk=autre_id).first()
                        deja_utilise_par = Individu.objects.filter(ent_id=valeur).first()
                        if deja_utilise_par:
                            if autre_individu:
                                echecs[autre_id] = deja_utilise_par
                        elif autre_individu:
                            autre_individu.ent_id = valeur
                            autre_individu.save()
                            nb_lies += 1

                if nb_lies > 1:
                    messages.success(request, f"{nb_lies} comptes ENT liés avec succès (individu + parent(s)). Ils seront désormais reconnus lors des prochains imports/synchronisations.")
                else:
                    messages.success(request, "Compte ENT lié avec succès. Cet individu sera désormais reconnu lors des prochains imports/synchronisations.")

                if echecs:
                    # Un message flash seul serait trop facile a manquer/oublier - on reste sur la
                    # page et on affiche l'echec directement a cote du parent concerne, en clair.
                    context = self.get_context_data()
                    context['nom_recherche'] = individu.nom
                    context['prenom_recherche'] = individu.prenom or ""
                    context['resultats'], context['erreur'] = self._rechercher(individu.nom, individu.prenom, idfamille, idindividu)
                    context['recherche_auto'] = False
                    for resultat in (context['resultats'] or []):
                        for membre in resultat.get('membres_enrichis', []):
                            correspondant = membre['individu_correspondant']
                            if correspondant and str(correspondant.pk) in echecs:
                                membre['echec'] = echecs[str(correspondant.pk)]
                    return self.render_to_response(context)

                return redirect(reverse('individu_resume', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))

            return redirect(reverse('individu_ent_lier', kwargs={'idfamille': idfamille, 'idindividu': idindividu}))
