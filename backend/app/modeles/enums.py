"""Énumérations métier.

Stockées en base sous forme de chaînes (et non de types ENUM PostgreSQL) :
ajouter une valeur ne nécessite alors aucune migration de type.
"""

from __future__ import annotations

from enum import Enum


class RoleMembre(str, Enum):
    ADMIN = "admin"          # gère l'organisation, les membres et l'abonnement
    ANALYSTE = "analyste"    # lance et exploite des investigations
    LECTEUR = "lecteur"      # consultation seule


class StatutOrganisation(str, Enum):
    ACTIVE = "active"
    SUSPENDUE = "suspendue"


class ModePivot(str, Enum):
    SUPERVISE = "supervise"   # chaque pivot est proposé et attend une validation humaine
    AUTOMATIQUE = "automatique"


class StatutAbonnement(str, Enum):
    ACTIF = "actif"
    EN_ATTENTE = "en_attente"
    EXPIRE = "expire"
    ANNULE = "annule"
    REMBOURSE = "rembourse"


class StatutInvestigation(str, Enum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    ERREUR = "erreur"
    ANNULEE = "annulee"


class StatutMaigret(str, Enum):
    TROUVE = "trouve"
    PROBABLE = "probable"
    ABSENT = "absent"
    ERREUR = "erreur"


class NiveauConfiance(str, Enum):
    FAIBLE = "faible"
    MOYEN = "moyen"
    ELEVE = "eleve"


class VerdictManuel(str, Enum):
    VALIDE = "valide"
    FAUX_POSITIF = "faux_positif"


class TypeDonnee(str, Enum):
    """Types d'informations extraites d'un profil par un module de site."""

    BIO = "bio"
    NOM_AFFICHE = "nom_affiche"
    NOM_REEL = "nom_reel"
    EMAIL = "email"
    PSEUDO_ALT = "pseudo_alt"
    LOCALISATION = "localisation"
    LIEN_EXTERNE = "lien_externe"
    AVATAR_URL = "avatar_url"
    AVATAR_PHASH = "avatar_phash"
    DATE_CREATION = "date_creation"
    TELEPHONE = "telephone"
    ENTREPRISE = "entreprise"
    LANGUE = "langue"
    NB_ABONNES = "nb_abonnes"


class TypePointDepart(str, Enum):
    """Nature d'un point de départ d'investigation.

    Une investigation peut démarrer avec plusieurs de ces éléments à la fois : ils se
    corroborent alors dès le premier tour, au lieu d'attendre un rebond.
    """

    PSEUDO = "pseudo"
    COMPTE = "compte"        # adresse d'un profil : https://github.com/quelquun
    EMAIL = "email"
    TELEPHONE = "telephone"
    NOM = "nom"
    ADRESSE = "adresse"


class TypeNoeud(str, Enum):
    PSEUDO = "pseudo"                  # le pseudonyme recherché (racine du graphe)
    COMPTE = "compte"                  # un profil trouvé sur un site
    EMAIL = "email"
    PSEUDO_ALT = "pseudo_alt"
    NOM = "nom"
    LOCALISATION = "localisation"
    LIEN = "lien"
    AVATAR = "avatar"
    TELEPHONE = "telephone"
    ENTREPRISE = "entreprise"


class TypeArete(str, Enum):
    POSSEDE_COMPTE = "possede_compte"                # pseudo -> compte
    INFORMATION_EXTRAITE = "information_extraite"    # compte -> donnée
    PIVOT_VERS = "pivot_vers"                        # donnée -> nouvelle recherche
    MEME_AVATAR = "meme_avatar"                      # compte <-> compte
    LIEN_CROISE = "lien_croise"                      # compte -> compte (lien explicite)
    EMAIL_PARTAGE = "email_partage"


class StatutPropositionPivot(str, Enum):
    EN_ATTENTE = "en_attente"
    ACCEPTEE = "acceptee"
    REFUSEE = "refusee"
    AUTOMATIQUE = "automatique"   # exécutée sans validation (mode automatique)


class ActionJournal(str, Enum):
    """Actions tracées pour la conformité RGPD et la traçabilité commerciale."""

    CONNEXION = "auth.connexion"
    CONNEXION_ECHOUEE = "auth.connexion_echouee"
    DECONNEXION = "auth.deconnexion"
    INSCRIPTION = "auth.inscription"
    CGU_ACCEPTEES = "auth.cgu_acceptees"
    INVESTIGATION_CREEE = "investigation.creee"
    INVESTIGATION_SUPPRIMEE = "investigation.supprimee"
    ENRICHISSEMENT_LANCE = "enrichissement.lance"
    PIVOT_LANCE = "pivot.lance"
    PIVOT_DECIDE = "pivot.decide"
    PROFIL_VERDICT = "profil.verdict"
    EXPORT = "investigation.export"
    MEMBRE_INVITE = "organisation.membre_invite"
    MEMBRE_RETIRE = "organisation.membre_retire"
    PLAN_CHANGE = "abonnement.plan_change"
    PURGE_RETENTION = "rgpd.purge_retention"
    SUPPRESSION_ORGANISATION = "rgpd.suppression_organisation"
