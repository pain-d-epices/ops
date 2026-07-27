"""Hachage des mots de passe avec Argon2id.

Argon2id est l'algorithme recommandé par l'OWASP : il résiste aux attaques par GPU,
contrairement à bcrypt qui reste acceptable mais moins robuste sur ce point.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Paramètres conformes aux recommandations OWASP 2024 (19 Mio de mémoire, 2 passes)
_hacheur = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)

LONGUEUR_MINIMALE_MOT_DE_PASSE = 12


class MotDePasseInvalide(ValueError):
    """Le mot de passe ne respecte pas la politique de sécurité."""


def hacher(mot_de_passe: str) -> str:
    return _hacheur.hash(mot_de_passe)


def verifier(mot_de_passe: str, empreinte: str) -> bool:
    try:
        return _hacheur.verify(empreinte, mot_de_passe)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def doit_etre_rehache(empreinte: str) -> bool:
    """Vrai si l'empreinte utilise des paramètres obsolètes (à réhacher à la prochaine connexion)."""
    try:
        return _hacheur.check_needs_rehash(empreinte)
    except (InvalidHashError, ValueError):
        return True


def valider_politique(mot_de_passe: str) -> None:
    """Vérifie la robustesse minimale. Lève MotDePasseInvalide si insuffisant.

    Politique volontairement fondée sur la longueur plutôt que sur des règles de
    composition : « au moins 12 caractères » protège mieux que « une majuscule et
    un chiffre », qui pousse surtout les utilisateurs vers « Password1! ».
    """
    if len(mot_de_passe) < LONGUEUR_MINIMALE_MOT_DE_PASSE:
        raise MotDePasseInvalide(
            f"Le mot de passe doit contenir au moins {LONGUEUR_MINIMALE_MOT_DE_PASSE} caractères."
        )
    if len(mot_de_passe) > 200:
        raise MotDePasseInvalide("Le mot de passe ne doit pas dépasser 200 caractères.")
    if mot_de_passe.lower() in _MOTS_DE_PASSE_INTERDITS:
        raise MotDePasseInvalide("Ce mot de passe est trop courant, choisissez-en un autre.")


_MOTS_DE_PASSE_INTERDITS = {
    "motdepasse123", "password1234", "azertyuiop12", "123456789012",
    "qwertyuiop12", "administrateur", "motdepasse!23",
}


def generer_jeton_aleatoire(longueur: int = 48) -> str:
    """Jeton aléatoire cryptographiquement sûr (invitations, rafraîchissement)."""
    return secrets.token_urlsafe(longueur)


def hacher_jeton(jeton: str) -> str:
    """Empreinte SHA-256 d'un jeton opaque.

    Argon2 est inutile ici : le jeton est déjà aléatoire et long, il n'y a pas de
    dictionnaire à attaquer. SHA-256 suffit et reste rapide à vérifier à chaque requête.
    """
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()
