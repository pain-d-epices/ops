"""Épreuve anti-automatisation à l'inscription, sans service tiers.

## Le principe

Le serveur pose une énigme dont la solution ne s'obtient qu'en essayant les nombres
un par un : « quel entier `n`, concaténé à ce sel, donne cette empreinte SHA-256 ? ».
Le navigateur la résout en une fraction de seconde ; un script qui veut
créer mille comptes doit la résoudre mille fois. Cela ne rend pas l'automatisation
impossible — rien ne la rend impossible — mais lui donne un coût, là où elle est
aujourd'hui gratuite.

## Pourquoi ce schéma plutôt qu'un CAPTCHA

Trois raisons, dans cet ordre :

1. **Aucun tiers n'est contacté.** Pour un outil d'investigation, faire passer chaque
   visiteur par un service de détection de robots reviendrait à lui révéler qui
   s'intéresse à l'outil. C'est le même raisonnement que le choix « APIs publiques
   uniquement » retenu pour les modules.
2. **Rien à payer, jamais** — ni palier gratuit à surveiller, ni compte à créer.
3. **Aucune énigme visuelle.** Rien à déchiffrer pour l'utilisateur : la résolution
   est silencieuse.

La contrepartie est assumée : un attaquant déterminé et outillé passera. L'objectif
est d'écarter l'abus opportuniste et la création de comptes en série, pas de résister
à une attaque ciblée. Le plafond de comptes par IP (voir `limiteur_entrant`) est le
second verrou, et il ne dépend pas de celui-ci.

## Format

Le format de charge utile est celui d'**Altcha** (projet libre, licence MIT). Le
serveur est écrit ici, sans dépendance ; le client aussi (voir `antiBot.ts`). Garder
le format standard permet de basculer plus tard sur le composant officiel sans
retoucher le serveur.

## Ce qui rend l'épreuve non contournable

- La signature HMAC empêche de fabriquer un défi soi-même : sans la clé secrète du
  serveur, impossible de produire un couple (défi, signature) valide.
- Le sel embarque un horodatage, ce qui borne la durée de vie du défi.
- Chaque défi résolu est marqué comme consommé dans Redis : le rejouer échoue. Sans
  cela, une seule résolution servirait à créer autant de comptes que voulu.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from app.config import config_metier, parametres
from app.infra.redis_client import client_redis, signaler_panne

journal = logging.getLogger(__name__)

ALGORITHME = "SHA-256"

#: Plage dans laquelle le nombre à trouver est tiré. Plus elle est haute, plus la
#: résolution coûte cher — au client honnête comme à l'attaquant. 50 000 représente
#: environ 300 ms dans un navigateur courant (mesuré : 240 ms pour 39 000 essais),
#: soit bien moins que le temps de saisie du formulaire, pendant lequel le calcul
#: tourne déjà en arrière-plan.
NOMBRE_MAXIMAL_DEFAUT = 50_000

#: Durée de validité d'un défi. Assez longue pour laisser remplir un formulaire,
#: assez courte pour qu'un stock de défis pré-résolus perde vite sa valeur.
VALIDITE_SECONDES_DEFAUT = 900


class PreuveInvalide(Exception):
    """La preuve fournie est absente, malformée, expirée, déjà utilisée ou fausse."""


@dataclass
class Defi:
    algorithm: str
    challenge: str
    salt: str
    signature: str
    maxnumber: int


def _cle_secrete() -> bytes:
    """Clé de signature des défis.

    Dérivée de la clé secrète de l'application, avec une étiquette propre : la même
    clé ne doit jamais servir à deux usages cryptographiques distincts.
    """
    return hashlib.sha256(b"anti-bot|" + parametres().cle_secrete.encode("utf-8")).digest()


def _nombre_maximal() -> int:
    return int(config_metier().obtenir("anti_abus.nombre_maximal", NOMBRE_MAXIMAL_DEFAUT))


def _validite() -> int:
    return int(config_metier().obtenir("anti_abus.validite_defi_secondes", VALIDITE_SECONDES_DEFAUT))


def _signer(defi: str) -> str:
    return hmac.new(_cle_secrete(), defi.encode("ascii"), hashlib.sha256).hexdigest()


def creer_defi() -> Defi:
    """Fabrique un défi : le serveur tire le nombre, le client devra le retrouver."""
    maximum = _nombre_maximal()
    nombre = secrets.randbelow(maximum + 1)
    # L'horodatage est dans le sel, donc couvert par la signature : le client ne peut
    # pas rajeunir un défi périmé.
    sel = f"{secrets.token_hex(12)}.{int(time.time())}"
    empreinte = hashlib.sha256(f"{sel}{nombre}".encode("ascii")).hexdigest()
    return Defi(
        algorithm=ALGORITHME,
        challenge=empreinte,
        salt=sel,
        signature=_signer(empreinte),
        maxnumber=maximum,
    )


def _horodatage_du_sel(sel: str) -> int | None:
    _, _, fin = sel.rpartition(".")
    try:
        return int(fin)
    except ValueError:
        return None


#: Repli mémoire des défis consommés, utilisé si Redis est injoignable.
#: `empreinte -> instant d'expiration`. Non partagé entre processus, donc moins étanche
#: que Redis, mais très supérieur à ne rien vérifier du tout.
_consommes_memoire: dict[str, float] = {}
_verrou_memoire = threading.Lock()


def _marquer_consomme_en_memoire(empreinte: str) -> bool:
    maintenant = time.time()
    with _verrou_memoire:
        # Purge opportuniste : évite que le dictionnaire croisse indéfiniment.
        for cle in [c for c, fin in _consommes_memoire.items() if fin <= maintenant]:
            del _consommes_memoire[cle]
        if empreinte in _consommes_memoire:
            return False
        _consommes_memoire[empreinte] = maintenant + _validite() + 60
        return True


def _marquer_consomme(empreinte: str) -> bool:
    """Marque ce défi comme utilisé. Rend False s'il l'était déjà.

    Si Redis est injoignable, on retombe sur une mémoire locale au processus plutôt
    que de laisser passer : perdre Redis ne doit pas faire disparaître la protection
    contre le rejeu, sans quoi une seule résolution suffirait à créer autant de
    comptes que voulu. Le service reste utilisable dans les deux cas.

    Même parti pris que `LimiteurMemoire` dans `infra/limiteur.py` : dégrader la
    portée, pas la règle.
    """
    client = client_redis()
    if client is None:
        return _marquer_consomme_en_memoire(empreinte)
    try:
        # SET NX : pose la clé seulement si elle n'existe pas — donc atomique.
        pose = client.set(f"anti_bot:utilise:{empreinte}", "1", nx=True, ex=_validite() + 60)
        return bool(pose)
    except Exception as exc:  # noqa: BLE001
        journal.warning("Redis en échec (%s) : détection du rejeu limitée au processus.", exc)
        signaler_panne()
        return _marquer_consomme_en_memoire(empreinte)


def verifier_preuve(charge_utile: str | None) -> None:
    """Valide la preuve envoyée par le client. Lève `PreuveInvalide` sinon.

    L'ordre des contrôles va du moins coûteux au plus coûteux, et la consommation du
    défi vient **en dernier** : un défi ne doit pas être brûlé par une preuve fausse,
    sans quoi un tiers pourrait invalider le défi d'un utilisateur légitime.
    """
    if not config_metier().obtenir("anti_abus.actif", True):
        return
    if not charge_utile:
        raise PreuveInvalide("Épreuve anti-robot absente.")

    try:
        donnees = json.loads(base64.b64decode(charge_utile).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PreuveInvalide("Épreuve anti-robot illisible.") from exc

    if not isinstance(donnees, dict):
        raise PreuveInvalide("Épreuve anti-robot illisible.")

    empreinte = str(donnees.get("challenge") or "")
    sel = str(donnees.get("salt") or "")
    signature = str(donnees.get("signature") or "")
    algorithme = str(donnees.get("algorithm") or "")
    nombre = donnees.get("number")

    if algorithme != ALGORITHME:
        raise PreuveInvalide("Épreuve anti-robot d'un type inattendu.")
    if not isinstance(nombre, int) or nombre < 0:
        raise PreuveInvalide("Épreuve anti-robot incomplète.")

    # 1. Le défi vient bien de nous — comparaison à temps constant.
    if not hmac.compare_digest(signature, _signer(empreinte)):
        raise PreuveInvalide("Épreuve anti-robot non authentique.")

    # 2. Il n'est pas périmé.
    emis_le = _horodatage_du_sel(sel)
    if emis_le is None:
        raise PreuveInvalide("Épreuve anti-robot malformée.")
    if time.time() - emis_le > _validite():
        raise PreuveInvalide("Épreuve anti-robot expirée. Réessayez.")

    # 3. La solution est la bonne.
    attendue = hashlib.sha256(f"{sel}{nombre}".encode("ascii")).hexdigest()
    if not hmac.compare_digest(attendue, empreinte):
        raise PreuveInvalide("Épreuve anti-robot non résolue.")

    # 4. Elle n'a pas déjà servi.
    if not _marquer_consomme(empreinte):
        raise PreuveInvalide("Épreuve anti-robot déjà utilisée. Réessayez.")


def reinitialiser_epreuves_consommees() -> None:
    """Oublie les épreuves déjà utilisées. Réservé aux tests."""
    with _verrou_memoire:
        _consommes_memoire.clear()
