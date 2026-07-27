"""Module d'enrichissement Keybase.

Keybase est un cas particulièrement intéressant : les utilisateurs y **prouvent
cryptographiquement** la possession de leurs comptes sur d'autres plateformes. Les
liens qui en sortent ne sont donc pas de simples déclarations mais des rattachements
vérifiés — c'est la meilleure source de pivots fiables de tout le système.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement

journal = logging.getLogger(__name__)


class ModuleKeybase(ModuleSite):
    nom = "keybase"
    libelle = "Keybase"
    domaines = ["keybase.io"]

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(
                "https://keybase.io/_/api/1.0/user/lookup.json",
                parametres_requete={"usernames": identifiant},
            )
        except (ErreurReseau, DebitDepasse) as exc:
            resultat.erreur = str(exc)
            return resultat

        comptes = (donnees or {}).get("them") if isinstance(donnees, dict) else None
        if not comptes or not isinstance(comptes, list) or not comptes[0]:
            resultat.erreur = f"Profil Keybase introuvable pour « {identifiant} »."
            return resultat

        contenu = comptes[0]
        resultat.donnees_brutes = contenu
        self._extraire(resultat, contenu, client)
        return resultat

    def _extraire(self, resultat: ResultatEnrichissement, contenu: dict[str, Any], client: ClientHttp) -> None:
        profil = contenu.get("profile") or {}
        resultat.ajouter(TypeDonnee.NOM_REEL, profil.get("full_name"), confiance=0.9)
        resultat.ajouter(TypeDonnee.BIO, profil.get("bio"))
        resultat.ajouter(TypeDonnee.LOCALISATION, profil.get("location"))

        basics = contenu.get("basics") or {}
        if basics.get("ctime"):
            resultat.ajouter(TypeDonnee.DATE_CREATION, int(basics["ctime"]))

        # Preuves cryptographiques de possession de comptes tiers : confiance maximale.
        for preuve in (contenu.get("proofs_summary") or {}).get("all") or []:
            service = (preuve.get("proof_type") or preuve.get("nametag") or "").lower()
            nom_compte = preuve.get("nametag")
            lien = preuve.get("service_url") or preuve.get("proof_url")

            if nom_compte:
                resultat.ajouter(
                    TypeDonnee.PSEUDO_ALT,
                    nom_compte,
                    confiance=1.0,
                    source=f"compte {service} prouvé cryptographiquement sur Keybase",
                )
            if lien:
                resultat.ajouter(
                    TypeDonnee.LIEN_EXTERNE,
                    lien,
                    confiance=1.0,
                    source=f"preuve Keybase ({service})",
                )

        bio = profil.get("bio")
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")

        avatar = (contenu.get("pictures") or {}).get("primary", {}).get("url")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
