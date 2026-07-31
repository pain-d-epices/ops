"""Domaines d'adresses électroniques jetables.

Servent à deux usages opposés, d'où ce module partagé :

- **À l'inscription**, ils sont refusés : une adresse jetable permet de créer des
  comptes gratuits en série sans jamais être joignable.
- **En investigation**, leur détection est au contraire une information utile sur la
  cible (voir le chercheur `email`) — on ne les écarte pas, on les signale.

La liste ne prétend pas à l'exhaustivité : il en existe des milliers, et de nouveaux
chaque semaine. Elle couvre les services les plus répandus, ce qui suffit à écarter
l'abus opportuniste. Contre un attaquant qui achète des domaines, c'est le plafond de
comptes par IP et l'épreuve anti-robot qui font le travail.

Comparaison par **suffixe** : les services jetables offrent en général des dizaines de
sous-domaines et d'alias sur le même domaine racine.
"""

from __future__ import annotations

DOMAINES_JETABLES: frozenset[str] = frozenset({
    # Les plus courants
    "mailinator.com", "yopmail.com", "yopmail.fr", "yopmail.net",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "sharklasers.com",
    "10minutemail.com", "10minutemail.net", "20minutemail.com",
    "tempmail.com", "temp-mail.org", "tempmail.net", "tempmailo.com",
    "throwawaymail.com", "trashmail.com", "trashmail.de", "trashmail.net",
    "getnada.com", "nada.email",
    "mailtothis.com", "maildrop.cc", "mailnesia.com", "mytemp.email",
    "dispostable.com", "fakeinbox.com", "spamgourmet.com", "mailcatch.com",
    "grr.la", "spam4.me", "byom.de",
    "moakt.com", "tmpmail.org", "tmpmail.net", "tmails.net",
    "emailondeck.com", "email-temp.com", "emailtemporaire.fr",
    "jetable.org", "jetable.net",
    "mohmal.com", "linshiyouxiang.net",
    "inboxkitten.com", "harakirimail.com", "mailpoof.com",
    "burnermail.io", "anonaddy.me", "mailbox.in.ua",
    "vpsboard.email", "cock.li", "firemailbox.club",
    "minuteinbox.com", "mail-temporaire.fr",
    "internxt.com", "tempr.email", "discard.email",
    "1secmail.com", "1secmail.net", "1secmail.org",
    "wwjmp.com", "esiix.com", "xojxe.com", "yoggm.com",
})


def est_domaine_jetable(adresse_ou_domaine: str) -> bool:
    """Vrai si l'adresse (ou le domaine seul) relève d'un service jetable."""
    valeur = (adresse_ou_domaine or "").strip().lower()
    if not valeur:
        return False
    domaine = valeur.rpartition("@")[2] if "@" in valeur else valeur
    domaine = domaine.strip(". ")
    if not domaine:
        return False
    return any(
        domaine == jetable or domaine.endswith("." + jetable)
        for jetable in DOMAINES_JETABLES
    )
