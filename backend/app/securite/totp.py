"""Authentification à deux facteurs par mot de passe à usage unique (TOTP, RFC 6238).

Aucun service tiers : le secret est généré et vérifié entièrement côté serveur, le QR
code aussi (bibliothèque `qrcode`, sans appel réseau). Compatible avec n'importe quelle
application d'authentification standard (Google Authenticator, Aegis, Bitwarden...).

## Chiffrement du secret en base

Le secret TOTP donne, à lui seul, la capacité de générer des codes valides
indéfiniment — contrairement à un mot de passe, il n'est pas haché (la vérification a
besoin de la valeur en clair). Il est donc chiffré avec Fernet (AES-128-CBC + HMAC),
clé dérivée du secret applicatif, avant d'être écrit dans `Utilisateur.totp_secret` :
une fuite de la base seule ne suffit pas à cloner le second facteur d'un compte.

## Activation en deux temps

`generer_secret` produit un secret et son QR code, mais ne l'active pas : c'est
`confirmer_activation` qui bascule `totp_actif` à True, seulement après vérification
d'un code réel. Sans cette confirmation, une erreur de scan laisserait l'utilisateur
verrouillé hors de son compte dès la prochaine connexion.
"""

from __future__ import annotations

import base64
import hashlib
import io

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken

from app.config import parametres

EMETTEUR = "Searcher"


class TotpRequis(Exception):
    """Le mot de passe est correct, mais le compte exige un second facteur.

    Distinct d'une erreur d'identifiants : le client sait qu'il doit présenter un
    champ de code plutôt que réafficher « identifiants incorrects ».
    """

#: Codes de secours à usage unique, fournis à l'activation, pour le cas où
#: l'utilisateur perd l'accès à son application d'authentification.
NOMBRE_CODES_SECOURS = 8


def _cle_fernet() -> Fernet:
    """Clé de chiffrement des secrets TOTP, dérivée de la clé secrète applicative.

    Fernet exige une clé de 32 octets encodée en base64 urlsafe — dérivation par
    SHA-256, même schéma que la signature des défis anti-robot (voir `anti_bot.py`) :
    une étiquette différente par usage, jamais la même clé brute pour deux emplois
    cryptographiques distincts.
    """
    empreinte = hashlib.sha256(b"totp-secret|" + parametres().cle_secrete.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(empreinte))


def chiffrer_secret(secret_brut: str) -> str:
    return _cle_fernet().encrypt(secret_brut.encode("ascii")).decode("ascii")


def dechiffrer_secret(secret_chiffre: str) -> str | None:
    """Rend le secret en clair, ou None si le chiffrement est invalide ou la clé a
    changé (config corrompue plutôt qu'exception qui casserait la connexion)."""
    try:
        return _cle_fernet().decrypt(secret_chiffre.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        return None


def generer_secret() -> str:
    """Un nouveau secret TOTP aléatoire, au format base32 attendu par pyotp."""
    return pyotp.random_base32()


def uri_provisionnement(secret_brut: str, email: str) -> str:
    return pyotp.TOTP(secret_brut).provisioning_uri(name=email, issuer_name=EMETTEUR)


def qr_code_base64(uri: str) -> str:
    """QR code du secret, encodé en PNG puis en base64 (affichable directement dans
    une balise `<img src="data:image/png;base64,...">`, sans fichier temporaire)."""
    image = qrcode.make(uri)
    tampon = io.BytesIO()
    image.save(tampon, format="PNG")
    return base64.b64encode(tampon.getvalue()).decode("ascii")


def code_valide(secret_brut: str, code: str) -> bool:
    """Vérifie un code à 6 chiffres, avec une fenêtre de tolérance d'une période
    (30 s) de part et d'autre : une horloge client légèrement désynchronisée est
    courante et ne doit pas bloquer une connexion légitime."""
    if not code or not code.strip().isdigit():
        return False
    return pyotp.TOTP(secret_brut).verify(code.strip(), valid_window=1)


def generer_codes_secours() -> list[str]:
    """Codes de secours à usage unique. Retournés en clair une seule fois, à
    l'activation : seule leur empreinte est conservée en base (voir `hacher_jeton`)."""
    import secrets as secrets_module

    return [f"{secrets_module.randbelow(10**8):08d}" for _ in range(NOMBRE_CODES_SECOURS)]
