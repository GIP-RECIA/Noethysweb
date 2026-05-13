# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, re
logger = logging.getLogger(__name__)
from core.models import Individu, Rattachement
from core.utils import utils_dates, utils_import_excel


def Importer(nom_fichier=""):
    importation = Import()
    importation.Start(nom_fichier=nom_fichier)


class Import(utils_import_excel.Importer):
    def Start(self, nom_fichier=""):
        data = self.Get_data_xlsx(nom_fichier, num_ligne_entete=0)

        dict_familles = {}
        for num_ligne, ligne in enumerate(data["A"], 0):
            if "né" in ligne["col1"]:
                # Identité
                regex = r"(?P<nom>[A-ZÀ-ÿ\s\(\)-]+)\s+(?P<prenom>[A-ZÀ-ÿ-]+)\s+(?P<genre>né|née)\s+le\s*:\s*(?P<date>\d{2}/\d{2}/\d{4})"
                match = re.search(regex, ligne["col1"], re.IGNORECASE)
                resultats = match.groupdict()
                enfant = {"nom": resultats["nom"].strip().upper(), "prenom": resultats["prenom"].strip().title(),
                          "genre": "G" if resultats["genre"] == "né" else "F",
                          "date_naiss": utils_dates.ConvertDateFRtoDate(resultats["date"])}

                # Parents
                parents = []
                for x in (1, 2):
                    regex_parent = r"(?P<genre>Père|Mère)\s*:\s*(?P<nom>[A-ZÀ-ÿ-]+)\s+(?P<prenom>[A-ZÀ-ÿ-]+)"
                    match = re.search(regex_parent, data["A"][num_ligne + x]["col1"])
                    if match:
                        resultats = match.groupdict()
                        tel_portable = data["A"][num_ligne + x]["col4"][5:] if len(data["A"][num_ligne + x]["col4"]) > 12 else None
                        tel_travail = data["A"][num_ligne + x]["col5"][6:] if len(data["A"][num_ligne + x]["col5"]) > 12 else None
                        parent = {"nom": resultats["nom"].strip().upper(), "prenom": resultats["prenom"].strip().title(),
                                  "genre": "M" if resultats["genre"] == "Père" else "F",
                                  "tel_mobile": tel_portable, "travail_tel": tel_travail}
                        parents.append(parent)

                # Adresse
                rue_resid = data["A"][num_ligne + 3]["col1"]
                cp_ville = data["A"][num_ligne + 4]["col1"]
                adresse = {"rue_resid": rue_resid.strip().title(),
                           "cp_resid": cp_ville[0:5],
                           "ville_resid": cp_ville[6:].strip().upper()}

                # Mémorisation de la famille ou rattachement à une famille existante
                code_famille = "%s_%s" % (adresse["rue_resid"], adresse["ville_resid"])
                if code_famille in dict_familles:
                    dict_familles[code_famille]["enfants"].append(enfant)
                else:
                    dict_familles[code_famille] = {"enfants": [enfant], "parents": parents, "adresse": adresse}

        for dict_famille in dict_familles.values():
            if dict_famille["parents"]:
                # Création de la famille
                famille = self.Creer_famille()

                # Création des parents
                for dict_parent in dict_famille["parents"]:
                    parents = []
                    individu = Individu.objects.create(
                        civilite=1 if dict_parent["genre"] == "M" else 3,
                        nom=dict_parent["nom"],
                        prenom=dict_parent["prenom"],
                        rue_resid=dict_famille["adresse"]["rue_resid"],
                        cp_resid=dict_famille["adresse"]["cp_resid"],
                        ville_resid=dict_famille["adresse"]["ville_resid"],
                        tel_mobile=dict_parent["tel_mobile"],
                        travail_tel=dict_parent["travail_tel"],
                    )
                    parents.append(individu)
                    Rattachement.objects.create(categorie=1, titulaire=True, famille=famille, individu=individu)
                    logger.debug("Création parent : %s" % individu)

                # Création des enfants
                for dict_enfant in dict_famille["enfants"]:
                    individu = Individu.objects.create(
                        civilite=4 if dict_enfant["genre"] == "G" else 5,
                        nom=dict_enfant["nom"],
                        prenom=dict_enfant["prenom"],
                        date_naiss=dict_enfant["date_naiss"],
                        adresse_auto=parents[0].pk,
                    )
                    Rattachement.objects.create(categorie=2, titulaire=False, famille=famille, individu=individu)
                    logger.debug("Création enfant : %s" % individu)

        # Maj des infos familles
        self.Maj_infos()
