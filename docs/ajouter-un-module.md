# Ajouter un module de site

Un module apprend à Ops à extraire des informations d'un site donné. Le système
est conçu pour qu'ajouter un site se limite à **créer un fichier** : aucun
enregistrement manuel, aucune modification du moteur.

## En résumé

1. Créez `backend/app/modules/monsite.py`
2. Héritez de `ModuleSite`, déclarez `nom`, `libelle`, `domaines`
3. Implémentez `enrichir()`
4. Ajoutez une limite de débit dans `config.yaml`
5. Écrivez un test avec un client HTTP simulé

Le registre découvre la classe au démarrage et l'applique automatiquement à tout profil
dont le domaine correspond.

---

## 1. Le squelette

```python
"""Module d'enrichissement MonSite."""

from __future__ import annotations

from typing import Any

from app.infra.http import ClientHttp, DebitDepasse, ErreurReseau
from app.modeles.enums import TypeDonnee
from app.modules.base import ModuleSite, ResultatEnrichissement


class ModuleMonSite(ModuleSite):
    nom = "monsite"                  # identifiant technique, unique
    libelle = "MonSite"              # nom affiché dans l'interface
    domaines = ["monsite.com"]       # sans « www. »

    def enrichir(self, url_profil: str, pseudo: str) -> ResultatEnrichissement:
        resultat = ResultatEnrichissement(module=self.nom)
        identifiant = self.pseudo_depuis_url(url_profil) or pseudo
        client = ClientHttp()

        try:
            donnees = client.obtenir_json(f"https://monsite.com/api/users/{identifiant}")
        except (ErreurReseau, DebitDepasse) as exc:
            # Une panne réseau n'est pas une absence de profil : on le signale
            resultat.erreur = str(exc)
            return resultat

        if not isinstance(donnees, dict):
            resultat.erreur = f"Profil introuvable pour « {identifiant} »."
            return resultat

        resultat.donnees_brutes = donnees
        self._extraire(resultat, donnees, client)
        return resultat

    def _extraire(self, resultat, donnees: dict[str, Any], client: ClientHttp) -> None:
        resultat.ajouter(TypeDonnee.NOM_AFFICHE, donnees.get("display_name"))
        resultat.ajouter(TypeDonnee.BIO, donnees.get("about"))
        resultat.ajouter(TypeDonnee.LOCALISATION, donnees.get("city"))
        resultat.ajouter(TypeDonnee.DATE_CREATION, donnees.get("joined_at"))
        resultat.ajouter(TypeDonnee.EMAIL, donnees.get("public_email"))

        # Toujours fouiller le texte libre : c'est là que se cachent les pivots
        bio = donnees.get("about")
        for email in self.extraire_emails(bio):
            resultat.ajouter(TypeDonnee.EMAIL, email, confiance=0.8, source="biographie")
        for lien in self.extraire_urls(bio):
            resultat.ajouter(TypeDonnee.LIEN_EXTERNE, lien, confiance=0.8, source="biographie")
        for mention in self.extraire_mentions(bio):
            resultat.ajouter(TypeDonnee.PSEUDO_ALT, mention, confiance=0.5, source="biographie")

        # L'avatar : signal de corrélation le plus puissant après l'adresse électronique
        avatar = donnees.get("avatar")
        if avatar:
            resultat.ajouter(TypeDonnee.AVATAR_URL, avatar)
            empreinte = self.hash_perceptuel(client.telecharger(avatar))
            if empreinte:
                resultat.ajouter(TypeDonnee.AVATAR_PHASH, empreinte, source=avatar)
```

C'est tout : le module est actif au prochain démarrage.

---

## 2. Types d'informations disponibles

| Type | Devient un nœud ? | Sert de pivot ? | Remarque |
|---|---|---|---|
| `BIO` | non | non | Comparée entre profils par la règle de similarité |
| `NOM_AFFICHE` | oui | non | |
| `NOM_REEL` | oui | oui | Pivoté seulement sous forme compacte (« jeanmartin ») |
| `EMAIL` | oui | oui | Signal de corrélation très fort |
| `PSEUDO_ALT` | oui | oui | Déclenche une nouvelle recherche Maigret |
| `LOCALISATION` | oui | non | |
| `LIEN_EXTERNE` | oui | oui | Pivote seulement si un module couvre le domaine |
| `AVATAR_URL` | non | non | |
| `AVATAR_PHASH` | oui | non | Empreinte perceptuelle, comparée entre profils |
| `DATE_CREATION` | non | non | Alimente la règle de cohérence temporelle |
| `TELEPHONE`, `ENTREPRISE` | oui | non | |
| `NB_ABONNES`, `LANGUE` | non | non | Informationnel |

**N'appelez pas `hash_perceptuel` sans passer par `client.telecharger`** : ce dernier
applique la limite de débit et plafonne la taille du fichier.

---

## 3. Le paramètre `confiance`

Il indique la fiabilité de l'extraction, pas celle du profil :

- `1.0` — champ structuré, explicitement déclaré par l'utilisateur (email public GitHub)
- `0.8` à `0.9` — champ déclaré mais interprété (lien dans un champ personnalisé)
- `0.5` à `0.6` — deviné depuis du texte libre (mention `@quelquechose` dans une bio)

Cette valeur pondère l'arête dans le graphe et l'ordre de traitement des pivots :
les plus fiables passent en premier si un plafond tronque la liste.

---

## 4. Déclarer la limite de débit

Dans `backend/config.yaml` :

```yaml
rate_limiting:
  par_domaine:
    "api.monsite.com":
      requetes_par_minute: 30
      rafale: 10
```

Cette limite est **globale, partagée entre tous les clients**. C'est ce qui protège
l'adresse IP du service d'un bannissement collectif quand plusieurs organisations
scannent le même site en même temps. En l'absence de déclaration, le réglage par défaut
s'applique (30 req/min).

---

## 5. Module nécessitant une clé API

```python
class ModuleMonSite(ModuleSite):
    necessite_cle_api = True

    def disponible(self) -> bool:
        # Un module indisponible est ignoré, sans faire échouer l'enrichissement
        # des autres sites.
        return bool(parametres().monsite_api_key)
```

Ajoutez la variable dans `app/config.py` (classe `Parametres`) et dans `.env.example`.

---

## 6. Écrire le test

Les tests de modules **ne doivent jamais toucher au réseau** : un test qui interroge le
site réel échouerait un jour de panne, pour une raison sans rapport avec votre code.

```python
def test_monsite_extrait_les_champs(monkeypatch):
    faux = FauxClient({"monsite.com/api/users/": {
        "display_name": "Jean Martin",
        "about": "Écrire à jean@exemple.fr",
        "avatar": "https://monsite.com/a.png",
    }})
    module = ModuleMonSite()
    monkeypatch.setattr("app.modules.monsite.ClientHttp", lambda *a, **k: faux)

    resultat = module.enrichir("https://monsite.com/jeanmartin", "jeanmartin")

    assert resultat.erreur is None
    assert "jean@exemple.fr" in resultat.valeurs(TypeDonnee.EMAIL)
```

`FauxClient` est défini dans `backend/tests/test_modules.py`.

---

## Avant d'ajouter un site : la question juridique

Ne développez un module que pour un site dont **l'API est publique et documentée**,
et dont les conditions d'utilisation n'interdisent pas l'accès automatisé.

Les plateformes fermées — X/Twitter, Instagram, Facebook, TikTok, LinkedIn — exigent
une authentification et **interdisent explicitement le scraping**. Un module pour ces
sites vous exposerait à trois problèmes cumulés :

1. bannissement des comptes utilisés pour l'accès ;
2. rupture de service à chaque changement de leur côté (fréquent, et sans préavis) ;
3. exposition juridique de qui opère l'instance.

C'est une décision commerciale, pas technique. Les vingt-deux modules couverts
aujourd'hui (GitHub, GitLab, Codeberg, Gitee, Reddit, Mastodon, Pixelfed, PeerTube,
Lemmy, Bluesky, Hacker News, Dev.to, Keybase, MixCloud, Steam, Lobsters, Wikipédia,
Liberapay, Goodreads, Letterboxd, Last.fm, Twitch) ont tous été retenus sur ce critère.

## Idées de modules sûrs à ajouter

Bitbucket, StackExchange.

## Écarté faute d'API publique fiable (juillet 2026)

Trois pistes de la feuille de route ont été examinées et volontairement laissées de
côté, faute d'un point d'accès public et stable :

- **SourceHut** — pas d'API de lecture anonyme ; seule une API GraphQL protégée par
  OAuth existe, ce qui reviendrait à exiger une clé pour un site classé « sans clé ».
- **Telegram (canaux publics)** — l'API Bot ne permet de consulter que les canaux
  dont le bot est membre ou les canaux publics par `@nom`, jamais un compte
  utilisateur individuel pris au hasard : peu utile pour enrichir un profil trouvé
  par pivot.
- **Ko-fi** — aucun point d'accès public en lecture ; l'API existante ne sert qu'aux
  webhooks de paiement.
