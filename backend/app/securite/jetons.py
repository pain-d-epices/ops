"""Émission et vérification des jetons JWT d'accès."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.config import parametres

ALGORITHME = "HS256"


class JetonInvalide(Exception):
    """Jeton absent, expiré, altéré ou de type inattendu."""


@dataclass(frozen=True)
class ContenuJeton:
    utilisateur_id: str
    organisation_id: str | None
    role: str | None
    expire_le: datetime


def creer_jeton_acces(
    utilisateur_id: str,
    organisation_id: str | None = None,
    role: str | None = None,
    duree: timedelta | None = None,
) -> str:
    """Jeton de courte durée transportant l'organisation active de la session.

    L'organisation figure dans le jeton mais n'est jamais une preuve suffisante :
    les endpoints revérifient systématiquement l'appartenance en base, faute de quoi
    un jeton volé permettrait d'accéder aux données d'une autre organisation.
    """
    params = parametres()
    duree = duree or timedelta(minutes=params.duree_jeton_acces_minutes)
    maintenant = datetime.now(timezone.utc)
    expiration = maintenant + duree

    charge = {
        "sub": utilisateur_id,
        "org": organisation_id,
        "role": role,
        "type": "acces",
        "iat": int(maintenant.timestamp()),
        "exp": int(expiration.timestamp()),
    }
    return jwt.encode(charge, params.cle_secrete, algorithm=ALGORITHME)


def decoder_jeton_acces(jeton: str) -> ContenuJeton:
    params = parametres()
    try:
        charge = jwt.decode(jeton, params.cle_secrete, algorithms=[ALGORITHME])
    except jwt.ExpiredSignatureError as exc:
        raise JetonInvalide("Jeton expiré.") from exc
    except jwt.PyJWTError as exc:
        raise JetonInvalide("Jeton invalide.") from exc

    if charge.get("type") != "acces":
        raise JetonInvalide("Type de jeton inattendu.")
    identifiant = charge.get("sub")
    if not identifiant:
        raise JetonInvalide("Jeton sans utilisateur.")

    return ContenuJeton(
        utilisateur_id=identifiant,
        organisation_id=charge.get("org"),
        role=charge.get("role"),
        expire_le=datetime.fromtimestamp(charge["exp"], tz=timezone.utc),
    )
