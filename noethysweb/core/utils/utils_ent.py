from core.models import Organisateur

def get_ent_users(nom, prenom):
    """
    Fonction pour rechercher des utilisateurs dans l'ENT

    Args:
        nom (str): Nom de famille
        prenom (str): Prénom

    Returns:
        list: Liste des familles ENT où l'utilisateur a été trouvé
    """
    try:
        exemple_users = [
                            {
                                "famille_id": 1,
                                "nom_famille": "Famille DUPONT",
                                "representants": [
                                    {
                                        "id_ent": "user179",
                                        "civilite": "Monsieur",
                                        "prenom": "Test10",
                                        "nom": "Test10",
                                        "email": "jean.dupont@mail.fr",
                                        "telephone": "0601020304",
                                    },
                                    {
                                        "id_ent": "user124",
                                        "civilite": "Madame",
                                        "prenom": "Marie",
                                        "nom": "DUPONT",
                                        "email": "marie.dupont@mail.fr",
                                        "telephone": "0605060708",
                                    },
                                ],
                                "enfants": [
                                    {
                                        "id_ent": "user131",
                                        "civilite": "Monsieur",
                                        "prenom": "Lucas",
                                        "nom": "DUPONT",
                                        "scolarite": {
                                            "date_debut": "2024-09-01",
                                            "date_fin": "2025-06-30",
                                            "ecole": {
                                                "id": 10,
                                                "nom": "Collège Victor Hugo",
                                                "rue": "12 rue de la République",
                                                "cp": "75001",
                                                "ville": "Paris",
                                                "tel": "0140203040",
                                                "fax": "0140203041",
                                                "mail": "contact@victorhugo.fr",
                                                "uai": "0751234A",
                                            },
                                            "classe": {
                                                "id": 101,
                                                "nom": "6ème A",
                                                "date_debut": "2024-09-01",
                                                "date_fin": "2025-06-30",
                                                "ecole_id": 10,
                                            },
                                            "niveau": {
                                                "id": 6,
                                                "ordre": 6,
                                                "nom": "Sixième",
                                                "abrege": "6ème",
                                            },
                                        },
                                    }
                                ],
                            },
                            {
                                "famille_id": 2,
                                "nom_famille": "Famille MARTIN",
                                "representants": [
                                    {
                                        "id_ent": "user2087",
                                        "civilite": "Monsieur",
                                        "prenom": "Test10",
                                        "nom": "Test10",
                                        "email": "Testent.Testent@mail.fr",
                                        "telephone": "0610101010",
                                    }
                                ],
                                "enfants": [
                                    {
                                        "id_ent": "user2087",
                                        "civilite": "Madame",
                                        "prenom": "TestEnfant10",
                                        "nom": "TestEnfant10",
                                        "scolarite": {
                                            "date_debut": "2024-09-01",
                                            "date_fin": "2025-06-30",
                                            "ecole": {
                                                "id": 20,
                                                "nom": "École élémentaire Jean Moulin",
                                                "rue": "25 avenue des Écoles",
                                                "cp": "69001",
                                                "ville": "Lyon",
                                                "tel": "0472101112",
                                                "fax": "0472101113",
                                                "mail": "contact@jeanmoulin.fr",
                                                "uai": "0695678B",
                                            },
                                            "classe": {
                                                "id": 201,
                                                "nom": "CE2",
                                                "date_debut": "2024-09-01",
                                                "date_fin": "2025-06-30",
                                                "ecole_id": 20,
                                            },
                                            "niveau": {
                                                "id": 3,
                                                "ordre": 3,
                                                "nom": "Cours Élémentaire 2",
                                                "abrege": "CE2",
                                            },
                                        },
                                    }
                                ],
                            },
                        ]

        result = []
        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur.ent_active:
            for famille in exemple_users:
                match_reps = [
                    rep for rep in famille["representants"]
                    if rep["nom"].lower() == nom.lower() and rep["prenom"].lower() == prenom.lower()
                ]
                match_enfants = [
                    enf for enf in famille["enfants"]
                    if enf["nom"].lower() == nom.lower() and enf["prenom"].lower() == prenom.lower()
                ]

                if match_reps or match_enfants:
                    # On garde toute la famille, même si un seul correspond
                    result.append(famille)

            return result
        else:
            return []

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return []

def get_ent_user_info(nom, prenom):
    """
    Recherche un utilisateur dans l'ENT (représentant ou enfant).
    Retourne uniquement ses infos, sans inclure la famille.
    """

    try:
        # Liste plate des utilisateurs (representants + enfants)
        exemple_users = [
            # Représentants DUPONT
            {
                "ent_id": "user179",
                "civilite": "Monsieur",
                "prenom": "Test10",
                "nom": "Test10",
                "email": "jean.dupont@mail.fr",
                "telephone": "0601020304",
            },
            {
                "ent_id": "user124",
                "civilite": "Madame",
                "prenom": "Marie",
                "nom": "DUPONT",
                "email": "marie.dupont@mail.fr",
                "telephone": "0605060708",
            },
            # Enfant DUPONT
            {
                "ent_id": "user131",
                "civilite": "Monsieur",
                "prenom": "Lucas",
                "nom": "DUPONT",
                "scolarite": {
                    "date_debut": "2024-09-01",
                    "date_fin": "2025-06-30",
                    "ecole": {
                        "id": 10,
                        "nom": "Collège Victor Hugo",
                        "rue": "12 rue de la République",
                        "cp": "75001",
                        "ville": "Paris",
                        "tel": "0140203040",
                        "fax": "0140203041",
                        "mail": "contact@victorhugo.fr",
                        "uai": "0751234A",
                    },
                    "classe": {
                        "id": 101,
                        "nom": "6ème A",
                        "date_debut": "2024-09-01",
                        "date_fin": "2025-06-30",
                        "ecole_id": 10,
                    },
                    "niveau": {
                        "id": 6,
                        "ordre": 6,
                        "nom": "Sixième",
                        "abrege": "6ème",
                    },
                },
            },
            # Représentant MARTIN
            {
                "ent_id": "user2087",
                "civilite": "Monsieur",
                "prenom": "Test10",
                "nom": "Test10",
                "email": "Testent.Testent@mail.fr",
                "telephone": "0610101010",
            },
            # Enfant MARTIN
            {
                "ent_id": "user2087",
                "civilite": "Madame",
                "prenom": "TestEnfant10",
                "nom": "TestEnfant10",
                "scolarite": {
                    "date_debut": "2024-09-01",
                    "date_fin": "2025-06-30",
                    "ecole": {
                        "id": 20,
                        "nom": "École élémentaire Jean Moulin",
                        "rue": "25 avenue des Écoles",
                        "cp": "69001",
                        "ville": "Lyon",
                        "tel": "0472101112",
                        "fax": "0472101113",
                        "mail": "contact@jeanmoulin.fr",
                        "uai": "0695678B",
                    },
                    "classe": {
                        "id": 201,
                        "nom": "CE2",
                        "date_debut": "2024-09-01",
                        "date_fin": "2025-06-30",
                        "ecole_id": 20,
                    },
                    "niveau": {
                        "id": 3,
                        "ordre": 3,
                        "nom": "Cours Élémentaire 2",
                        "abrege": "CE2",
                    },
                },
            },
        ]

        organisateur = Organisateur.objects.filter(pk=1).first()
        if not organisateur or not organisateur.ent_active:
            return []

        # Recherche de l’utilisateur
        result = [
            user for user in exemple_users
            if user["nom"].lower() == nom.lower() and user["prenom"].lower() == prenom.lower()
        ]

        return result

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return []

def get_ent_user_info_by_ent_id(ent_id):
    """
    Recherche un utilisateur dans l'ENT (représentant ou enfant).
    Retourne uniquement ses infos, sans inclure la famille.
    """

    try:
        # Liste plate des utilisateurs (representants + enfants)
        exemple_users = [
            # Représentants DUPONT
            {
                "ent_id": "user179",
                "civilite": "Monsieur",
                "prenom": "Test10",
                "nom": "Test10",
                "email": "jean.dupont@mail.fr",
                "telephone": "0601020304",
            },
            {
                "ent_id": "user124",
                "civilite": "Madame",
                "prenom": "Marie",
                "nom": "DUPONT",
                "email": "marie.dupont@mail.fr",
                "telephone": "0605060708",
            },
            {
                "ent_id": "user129",
                "civilite": "Monsieur",
                "prenom": "Test11",
                "nom": "Test11",
                "email": "marie.dupont@mail.fr",
                "telephone": "0605060708",
            },
            # Enfant DUPONT
            {
                "ent_id": "user125",
                "civilite": "Monsieur",
                "prenom": "Lucas",
                "nom": "DUPONT",
                "scolarite": {
                    "date_debut": "2024-09-01",
                    "date_fin": "2025-06-30",
                    "ecole": {
                        "id": 10,
                        "nom": "Collège Victor Hugo",
                        "rue": "12 rue de la République",
                        "cp": "75001",
                        "ville": "Paris",
                        "tel": "0140203040",
                        "fax": "0140203041",
                        "mail": "contact@victorhugo.fr",
                        "uai": "0751234A",
                    },
                    "classe": {
                        "id": 101,
                        "nom": "6ème A",
                        "date_debut": "2024-09-01",
                        "date_fin": "2025-06-30",
                        "ecole_id": 10,
                    },
                    "niveau": {
                        "id": 6,
                        "ordre": 6,
                        "nom": "Sixième",
                        "abrege": "6ème",
                    },
                },
            },
            # Représentant MARTIN
            {
                "ent_id": "user2087",
                "civilite": "Monsieur",
                "prenom": "Test10",
                "nom": "Test10",
                "email": "Testent.Testent@mail.fr",
                "telephone": "0610101010",
            },
            # Enfant MARTIN
            {
                "ent_id": "user2087",
                "civilite": "Madame",
                "prenom": "TestEnfant10",
                "nom": "TestEnfant10",
                "scolarite": {
                    "date_debut": "2024-09-01",
                    "date_fin": "2025-06-30",
                    "ecole": {
                        "id": 20,
                        "nom": "École élémentaire Jean Moulin",
                        "rue": "25 avenue des Écoles",
                        "cp": "69001",
                        "ville": "Lyon",
                        "tel": "0472101112",
                        "fax": "0472101113",
                        "mail": "contact@jeanmoulin.fr",
                        "uai": "0695678B",
                    },
                    "classe": {
                        "id": 201,
                        "nom": "CE2",
                        "date_debut": "2024-09-01",
                        "date_fin": "2025-06-30",
                        "ecole_id": 20,
                    },
                    "niveau": {
                        "id": 3,
                        "ordre": 3,
                        "nom": "Cours Élémentaire 2",
                        "abrege": "CE2",
                    },
                },
            },
        ]

        organisateur = Organisateur.objects.filter(pk=1).first()
        if not organisateur or not organisateur.ent_active:
            return []

        # Recherche de l’utilisateur
        result = [
            user for user in exemple_users
            if user["ent_id"].lower() == ent_id.lower()
        ]

        return result[0]

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return None


def get_ent_collaborateur(nom, prenom):
    """
    Fonction pour rechercher de Personnel Education National dans l'ENT

    Args:
        nom (str): Nom de famille
        prenom (str): Prénom

    Returns:
        list: Liste des enseignats ENT
    """
    try:
        exemple_users = [
                            {
                                "ent_id": "user101",
                                "nom": "TestCollabNom",
                                "prenom": "TestCollaPrenNom",
                                "mail": "jean.dupont@mail.fr",
                                "profil": "Parent",
                                "ecole": "Collège Victor Hugo",
                                "rue": "12 rue de la République",
                                "code_postal": "75012",
                                "ville": "Paris",
                                "travail_tel": "0145236789",
                                "travail_mail": "jean.dupont@entreprise.fr",
                                "tel_domicile": "0145789654",
                                "tel_mobile": "0601020304"
                            },
                            {
                                "ent_id": "user102",
                                "nom": "TestCollabNom",
                                "prenom": "TestCollaPrenNom",
                                "mail": "sophie.martin@mail.fr",
                                "profil": "Tuteur",
                                "ecole": "Collège Victor Hugo",
                                "rue": "45 avenue de la Liberté",
                                "code_postal": "69007",
                                "ville": "Lyon",
                                "travail_tel": "0478234567",
                                "travail_mail": "sophie.martin@entreprise.fr",
                                "tel_domicile": "0478456987",
                                "tel_mobile": "0698765432"
                            },
                            {
                                "ent_id": "user103",
                                "nom": "Bernard",
                                "prenom": "Luc",
                                "mail": "luc.bernard@mail.fr",
                                "profil": "Parent",
                                "ecole": "Lycée Louis Pasteur",
                                "rue": "78 boulevard Saint-Michel",
                                "code_postal": "34000",
                                "ville": "Montpellier",
                                "travail_tel": "0499554433",
                                "travail_mail": "luc.bernard@entreprise.fr",
                                "tel_domicile": "0499678877",
                                "tel_mobile": "0678901234"
                            },
                            {
                                "ent_id": "user104",
                                "nom": "Bersellou",
                                "prenom": "Mustapha",
                                "mail": "jean.dupont@mail.fr",
                                "profil": "Parent",
                                "ecole": "Collège Victor Hugo",
                                "rue": "12 rue de la République",
                                "code_postal": "75012",
                                "ville": "Paris",
                                "travail_tel": "0145236789",
                                "travail_mail": "mus.bers@entreprise.fr",
                                "tel_domicile": "0145789654",
                                "tel_mobile": "0601020304"
                            },
                        ]
        result = []
        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur.ent_active:
            result = [
                        user for user in exemple_users
                        if user["nom"].lower() == nom.lower() and user["prenom"].lower() == prenom.lower()
                    ]
            return result
        else:
            return []

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return []
    
def get_collaborateur_by_ent_id(ent_id):
    """
    Fonction pour rechercher de Personnel Education National dans l'ENT

    Args:
        nom (str): Nom de famille
        prenom (str): Prénom

    Returns:
        list: Liste des enseignats ENT
    """
    try:
        exemple_users = [
                            {
                                "ent_id": "user101",
                                "nom": "TestCollabNom",
                                "prenom": "TestCollaPrenNom",
                                "mail": "jean.dupont@mail.fr",
                                "profil": "Parent",
                                "ecole": "Collège Victor Hugo",
                                "rue": "12 rue de la République",
                                "code_postal": "75012",
                                "ville": "Paris",
                                "travail_tel": "0145236789",
                                "travail_mail": "jean.dupont@entreprise.fr",
                                "tel_domicile": "0145789654",
                                "tel_mobile": "0601020304"
                            },
                            {
                                "ent_id": "user102",
                                "nom": "TestCollabNom",
                                "prenom": "TestCollaPrenNom",
                                "mail": "sophie.martin@mail.fr",
                                "profil": "Tuteur",
                                "ecole": "Collège Victor Hugo",
                                "rue": "45 avenue de la Liberté",
                                "code_postal": "69007",
                                "ville": "Lyon",
                                "travail_tel": "0478234567",
                                "travail_mail": "sophie.martin@entreprise.fr",
                                "tel_domicile": "0478456987",
                                "tel_mobile": "0698765432"
                            },
                            {
                                "ent_id": "user103",
                                "nom": "Bernard",
                                "prenom": "Luc",
                                "mail": "luc.bernard@mail.fr",
                                "profil": "Parent",
                                "ecole": "Lycée Louis Pasteur",
                                "rue": "78 boulevard Saint-Michel",
                                "code_postal": "34000",
                                "ville": "Montpellier",
                                "travail_tel": "0499554433",
                                "travail_mail": "luc.bernard@entreprise.fr",
                                "tel_domicile": "0499678877",
                                "tel_mobile": "0678901234"
                            },
                            {
                                "ent_id": "user104",
                                "nom": "Bersellou",
                                "prenom": "Mustapha",
                                "mail": "jean.dupont@mail.fr",
                                "profil": "Parent",
                                "ecole": "Collège Victor Hugo",
                                "rue": "12 rue de la République",
                                "code_postal": "75012",
                                "ville": "Paris",
                                "travail_tel": "0145236789",
                                "travail_mail": "mus.bers@entreprise.fr",
                                "tel_domicile": "0145789654",
                                "tel_mobile": "0601020304"
                            },
                        ]

        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur.ent_active:
            for collab in exemple_users:
                if collab["ent_id"] == ent_id:
                    return collab
            return None
        else:
            return None

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return []

def get_ent_ecole(uai):
    """
    Fonction pour rechercher une école dans l'ENT par son UAI

    Args:
        uai (str): identifiant UAI de l'école

    Returns:
        dict: école trouvée avec cet UAI ou None si non trouvée
    """
    try:
        exemple_ecoles = [
                            {
                                "uai": "0751234A",
                                "nom": "École Primaire Jean Moulin",
                                "rue": "12 rue de la République",
                                "cp": "75012",
                                "ville": "Paris",
                                "telephone": "0145236789",
                                "mail": "contact@ecole-jeanmoulin.fr",
                                "niveaux": [
                                    {"ordre": 1, "nom": "CP", "abrege": "CP"},
                                    {"ordre": 2, "nom": "CE1", "abrege": "CE1"},
                                ],
                                "classes": [
                                    {"nom": "CP A", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CP"},
                                    {"nom": "CP B", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CP"},
                                    {"nom": "CE1 A", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CE1"},
                                ],
                            },
                            {
                                "uai": "0695678B",
                                "nom": "Collège Victor Hugo",
                                "rue": "25 avenue des Lumières",
                                "cp": "69008",
                                "ville": "Lyon",
                                "telephone": "0472983456",
                                "mail": "secretariat@college-vhugo.fr",
                                "niveaux": [
                                    {"ordre": 6, "nom": "6ème", "abrege": "6e"},
                                    {"ordre": 5, "nom": "5ème", "abrege": "5e"},
                                ],
                                "classes": [
                                    {"nom": "6ème 1", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "6ème"},
                                    {"nom": "6ème 2", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "6ème"},
                                    {"nom": "5ème A", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "5ème"},
                                    {"nom": "5ème B", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "5ème"},
                                ],
                            },
                            {
                                "uai": "1837227A",
                                "nom": "École Primaire Jean Moulin 2",
                                "rue": "12 rue de la République",
                                "cp": "75012",
                                "ville": "Paris",
                                "telephone": "0145236789",
                                "mail": "contact@ecole-jeanmoulin.fr",
                                "niveaux": [
                                    {"ordre": 1, "nom": "CP", "abrege": "CP"},
                                    {"ordre": 2, "nom": "CE1", "abrege": "CE1"},
                                ],
                                "classes": [
                                    {"nom": "CP A", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CP"},
                                    {"nom": "CP B", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CP"},
                                    {"nom": "CE1 A", "date_debut": "2024-09-01", "date_fin": "2025-07-05", "niveau_nom": "CE1"},
                                ],
                            },
                        ]


        organisateur = Organisateur.objects.filter(pk=1).first()
        if organisateur and organisateur.ent_active:
            for ecole in exemple_ecoles:
                if ecole["uai"] == uai:
                    return ecole
            return None
        else:
            return None

    except Exception as e:
        print(f"Erreur lors de la recherche ENT: {e}")
        return None
