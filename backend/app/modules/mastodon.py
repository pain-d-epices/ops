"""Module d'enrichissement Mastodon (et instances compatibles).

Mastodon étant fédéré, le domaine varie d'une instance à l'autre : le module
interroge l'instance présente dans l'URL du profil, via l'API publique standard.
Les champs personnalisés (« fields ») sont particulièrement riches en pivots — les
utilisateurs y déclarent souvent leur site, leur GitHub ou leur email.

`ModulePixelfed` hérite directement de cette classe : Pixelfed expose volontairement
la même API que Mastodon, pour que les applications clientes existantes fonctionnent
sans adaptation. Seuls `nom`, `libelle` et `domaines` diffèrent.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)

MOTIF_BALISE = re.compile(r"<[^>]+>")
# Balises de bloc : elles séparent réellement deux morceaux de texte
MOTIF_BALISE_BLOC = re.compile(r"</?(?:p|br|div|li|ul|ol|h[1-6])\b[^>]*>", re.IGNORECASE)


def nettoyer_html(texte: str | None) -> str:
    """Retire les balises HTML d'une biographie (Mastodon renvoie du HTML).

    Les balises en ligne sont supprimées **sans** insérer d'espace : Mastodon découpe
    ses liens en plusieurs `<span>` (« <span>https://</span><span>github.com/x</span> »)
    et un espace inséré au milieu casserait l'URL — donc le pivot qui en découle.
    Seules les balises de bloc deviennent une espace, car elles séparent vraiment
    deux morceaux de texte.
    """
    if not texte:
        return ""
    avec_separateurs = MOTIF_BALISE_BLOC.sub(" ", texte)
    sans_balise = MOTIF_BALISE.sub("", avec_separateurs)
    remplacements = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}
    for entite, caractere in remplacements.items():
        sans_balise = sans_balise.replace(entite, caractere)
    return " ".join(sans_balise.split())


class ModuleMastodon(ModuleSite):
    nom = "mastodon"
    libelle = "Mastodon"
    # Instances les plus courantes ; les autres restent gérées si Maigret les remonte
    # sous l'un de ces domaines. Ajouter une instance = ajouter une ligne ici.
    domaines = [
        "mastodon.social", "mastodon.online", "mstdn.social", "fosstodon.org",
        "hachyderm.io", "piaille.fr", "framapiaf.org", "mamot.fr", "mastodon.world",
    ]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        analyse = urlparse(url_profil if "://" in url_profil else f"https://{url_profil}")
        instance = analyse.netloc
        identifiant = (self.pseudo_depuis_url(url_profil) or pseudo).lstrip("@")

        if not instance:
            resultat.erreur = f"Instance {self.libelle} indéterminable depuis l'URL."
            return resultat

        client = ClientHttp()
        try:
            donnees = client.obtenir_json(
                f"https://{instance}/api/v1/accounts/lookup",
                parametres_requete={"acct": identifiant},
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict) or not donnees.get("username"):
            resultat.erreur = f"Compte {self.libelle} introuvable pour « {identifiant}@{instance} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("display_name"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("created_at"))
        resultat.ajouter(TypeDonnee.NB_ABONNES, donnees.get("followers_count"))

        bio = nettoyer_html(donnees.get("note"))
        resultat.ajouter(TypeDonnee.BIO, bio)

        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        # Champs personnalisés : les utilisateurs y déclarent explicitement leurs
        # autres présences en ligne, ce qui en fait la meilleure source de pivots.
        for champ in donnees.get("fields") or []:
            valeur = nettoyer_html(champ.get("value"))
            nom_champ = (champ.get("name") or "").lower()
            if not valeur:
                continue
            if "@" in valeur and " " not in valeur and "." in valeur.split("@")[-1]:
                resultat.ajouter(TypeDonnee.EMAIL, valeur, confiance=0.9, source=f"champ « {nom_champ} »")
            elif valeur.startswith("http"):
                resultat.ajouter(
                    TypeDonnee.LIEN_EXTERNE, valeur, confiance=0.95, source=f"champ « {nom_champ} »"
                )
                pseudo_deduit = self.pseudo_depuis_url(valeur)
                if pseudo_deduit:
                    resultat.ajouter(
                        TypeDonnee.PSEUDO_ALT,
                        pseudo_deduit,
                        confiance=0.7,
                        source=f"lien déclaré dans le champ « {nom_champ} »",
                    )
            elif nom_champ in {"localisation", "location", "lieu", "ville"}:
                resultat.ajouter(TypeDonnee.LOCALISATION, valeur, confiance=0.9)

        avatar = donnees.get("avatar_static") or donnees.get("avatar")
        if avatar and "missing.png" not in avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
