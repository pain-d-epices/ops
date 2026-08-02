# Searcher — SaaS OSINT de recherche et corrélation de pseudonymes

Application web multi-clients qui recherche un pseudonyme sur des milliers de sites,
détermine quels comptes appartiennent réellement à la même personne, en extrait des
informations exploitables, et restitue l'ensemble sous forme de graphe de relations.

> ## ⚠️ Cadre légal d'utilisation
>
> Cet outil traite des **données personnelles de tiers qui n'ont pas consenti à leur
> collecte**. Son utilisation n'est licite que dans un cadre légitime et légal :
> enquête autorisée, journalisme d'investigation, sécurité défensive, recherche de
> fraude, ou vérification avec le consentement de la personne concernée.
>
> **Sont formellement exclus** : le harcèlement, le pistage d'une personne privée, la
> surveillance non consentie, la constitution de fichiers à l'insu des intéressés, ou
> tout usage contraire au RGPD.
>
> Chaque recherche est **journalisée** avec son auteur, son organisation, sa cible et
> son horodatage. Les résultats sont des **estimations probabilistes, jamais des
> certitudes** : ils doivent être vérifiés avant toute exploitation. L'utilisateur est
> seul responsable de la légalité de son usage.
>
> Avant toute mise en service commerciale, faites valider par un juriste votre base
> légale de traitement (intérêt légitime) et réalisez une analyse d'impact (AIPD).

---

## Ce que fait l'outil

1. **Recherche** — lance [Maigret](https://github.com/soxoj/maigret) sur un pseudonyme et récupère les comptes trouvés, complété par une recherche web ouverte (DuckDuckGo) et une recherche dans l'index public du réseau Tor (Ahmia — jamais de connexion Tor depuis le serveur, voir [`backend/app/moteur/sources/`](backend/app/moteur/sources/)). Une investigation peut aussi partir de plusieurs éléments à la fois : adresse électronique, numéro de téléphone, adresse d'un compte connu, adresse postale. Le type de chaque élément saisi est **deviné automatiquement**, et reste modifiable.
2. **Corrèle** — attribue à chaque compte un score de confiance calculé par des règles pondérées (similarité du pseudonyme, avatar identique, adresse partagée, liens réciproques, cohérence des dates), et écarte les faux positifs.
3. **Enrichit** — applique un module par site pour extraire biographie, avatar, localisation, liens, date de création, autres pseudonymes. Vingt-deux sites couverts : GitHub, GitLab, Codeberg, Gitee, Reddit, Mastodon, Pixelfed, PeerTube, Lemmy, Bluesky, Hacker News, Dev.to, Keybase, MixCloud, Steam, Lobsters, Wikipédia, Liberapay, Goodreads, Letterboxd, Last.fm, Twitch (ces deux derniers nécessitent une clé API gratuite).
4. **Pivote** — repart automatiquement des informations découvertes (un pseudonyme dans une bio relance une recherche, un lien déclenche un enrichissement direct), dans la limite de la profondeur autorisée.
5. **Visualise** — restitue le tout en graphe interactif : nœuds = identités et informations, arêtes = relations découvertes.

### Le score est explicable

Chaque score s'accompagne du détail de son calcul : « 87 % — pseudonyme identique
(+40), avatar identique à GitHub (+30), adresse partagée avec Mastodon (+17) ».
Un analyste peut donc **contester** une conclusion plutôt que la subir. C'est
indispensable quand la sortie sert à identifier une personne réelle.

Quatre garde-fous limitent les faux positifs :

- **un signal unique ne peut jamais atteindre la confiance élevée** — un pseudonyme
  identique est un indice, pas une preuve : sur un pseudonyme courant, des dizaines de
  personnes sans lien entre elles le partagent ;
- **l'identité déclarée peut faire *baisser* un score** : un compte qui annonce un nom
  sans rapport avec le pseudonyme recherché ni avec les autres comptes est déclassé
  comme homonyme probable (voir ci-dessous) ;
- les résultats obtenus par recherche approximative et les sites connus pour répondre
  « ce compte existe » à n'importe quelle requête sont **pénalisés** ;
- un compte sur **site à caractère sexuel** reste en confiance faible tant qu'aucune
  preuve indépendante du pseudonyme ne le corrobore.

### L'homonymie est le vrai mode d'échec, et elle est traitée

Vérification manuelle du 02/08/2026, en ouvrant les comptes remontés sur
« torvalds » : **ils existent presque tous** — 73 % des URL testées renvoient un vrai
profil consultable. Le problème n'est donc pas que l'outil invente des comptes, mais
qu'il en trouve **appartenant à d'autres personnes** : `instagram.com/torvalds`
déclare « Marco Migozzi », `untappd.com/torvalds` « Torvald Storaas », le compte Steam
« WTF Gaming », domicilié en Indonésie.

Le moteur exploite désormais ces noms au lieu de les ignorer. Trois précautions, toutes
tirées de cas réels mesurés :

- deux comptes portant le **même nom étranger** au pseudonyme ne se corroborent pas :
  Instagram et Pinterest déclaraient tous deux « Marco Migozzi » — c'est l'indice qu'un
  tiers possède ce pseudonyme sur plusieurs plateformes, pas qu'il s'agit de la cible ;
- un nom **recopié du pseudonyme** par le site (« Torvalds Torvalds » sur SoundCloud)
  ne compte pas : ce serait la même information votant deux fois ;
- un nom d'un seul mot (« NaraKa ») n'est pas une identité civile : la règle s'abstient
  plutôt que de pénaliser un compte légitime.

Résultat mesuré sur la même recherche : la liste exploitable passe de **123 comptes
indifférenciés à 5**, les homonymes vérifiés retombant de « confiance moyenne » à 23–43 %.

### Les comptes non corroborés sont repliés

Un compte qui ne repose que sur son pseudonyme n'est pas un résultat, c'est une piste.
L'interface les regroupe donc derrière un « *N* comptes au pseudonyme identique, non
vérifiés », dépliable d'un clic. Les afficher au même rang que les comptes corroborés
noyait les quelques trouvailles utiles et laissait croire à une conclusion.

---

## Paliers d'abonnement

| | Gratuit | Starter | Pro | Entreprise |
|---|---|---|---|---|
| Prix mensuel | 0 € | 29 € | 99 € | 299 € |
| **Recherches / mois** | 10 | 100 | 500 | 2500 |
| **Rebonds (profondeur de pivot)** | 1 | 2 | 5 | 10 |
| **Sites analysés par recherche** | 100 | 1000 | tous | tous |
| Enrichissements / mois | 50 | 500 | 5000 | 50 000 |
| Utilisateurs | 1 | 3 | 10 | 50 |
| Recherche par pseudonyme | ✅ | ✅ | ✅ | ✅ |
| Recherche par e-mail | ✅ | ✅ | ✅ | ✅ |
| Recherche par téléphone, adresse, compte | ❌ | ✅ | ✅ | ✅ |
| **Résultats de sites sensibles** | ❌ | ✅ | ✅ | ✅ |
| Modules par site | ✅ (50/mois) | ✅ | ✅ | ✅ |
| Recherche web et dark web | ❌ | ✅ | ✅ | ✅ |
| Éléments de départ par investigation | 1 | 2 | 5 | illimité |
| Pivot | supervisé (1 niveau) | supervisé | automatique | automatique |
| Export CSV / PDF | ❌ | CSV | CSV + PDF | CSV + PDF |

> **Accès API : pas construit, et retiré de la grille.** Le code de fonctionnalité
> (`API_PUBLIQUE`) existe mais rien ne le vérifie — ni clé, ni authentification
> machine. Il n'est donc plus accordé au palier Entreprise ni affiché sur la page
> Abonnement : annoncer une fonctionnalité inexistante sur un palier à 299 €/mois est
> un risque commercial et juridique direct. À rétablir le jour où elle existera.
> État des lieux et travail restant : [docs/acces-api.md](docs/acces-api.md).

Le palier gratuit sert la **démonstration**. Il incluait auparavant 15 recherches sur
200 sites, mais ni enrichissement ni rebond — et rendait donc une liste de comptes tous
notés à l'identique (mesuré le 02/08/2026 : 84 résultats, 82 à 65 %, **aucun** en
confiance élevée). Il prouvait exactement le contraire de ce que le produit vend. Il
offre désormais moins de volume mais une chaîne complète : enrichissement des comptes
trouvés et un niveau de rebond, de quoi juger sur pièces. Même recherche après refonte :
52 comptes, dont **5 en confiance élevée** et 3 rebonds proposés.

Ce qui reste payant : le volume, la profondeur au-delà d'un niveau, le rebond
**automatique** (le gratuit propose, il n'exécute jamais de lui-même), la couverture en
sites, les types de recherche spécialisés, la recherche web étendue, les exports et les
sites sensibles.

Les **sites sensibles** (pornographie) sont exclus du palier gratuit : c'est une limite
commerciale, mais aussi une précaution, ce type de compte étant la donnée la plus
sensible qu'une investigation puisse révéler. Voir
[`backend/app/moteur/sites_sensibles.py`](backend/app/moteur/sites_sensibles.py).
Sur les paliers payants, un tel compte reste par ailleurs en **confiance faible** tant
qu'il ne repose que sur un pseudonyme identique : l'imputer à quelqu'un sur cette seule
base serait diffamatoire, et au RGPD un traitement de données de l'article 9 fondé sur
un faux positif.

Ces restrictions sont appliquées **côté serveur** (endpoints *et* tâches de fond),
jamais seulement par masquage d'un bouton.

Les quotas se modifient directement en base, sans toucher au code : voir
[`backend/app/facturation/plans.py`](backend/app/facturation/plans.py) pour les valeurs
initiales, appliquées par `python -m app.scripts.initialiser_plans`.

---

## Installation

### Prérequis

- Docker et Docker Compose (recommandé), **ou** Python 3.11+, PostgreSQL 16 et Redis 7
- 2 Go de RAM minimum, 4 Go recommandés (Maigret est gourmand pendant les scans)

### Démarrage en un clic (développement local sous Windows)

Une fois l'installation initiale faite (dépendances Python/Node, `.env` configuré —
voir ci-dessous), double-cliquez sur **`demarrer.bat`** à la racine du projet. Il
démarre PostgreSQL et Redis (Docker), l'API, l'interface web puis le worker de tâches
dans des fenêtres séparées, et ouvre le navigateur automatiquement.

Le script attend que chaque brique réponde réellement avant de passer à la suivante
(PostgreSQL via `pg_isready`, API via `/api/sante`, interface via une requête HTTP) :
le navigateur ne s'ouvre donc jamais sur une application encore en train de démarrer.

Le worker est lancé **en dernier**, volontairement : il charge la base Maigret de 3221
sites, ce qui occupe le processeur et le disque pendant environ deux minutes. L'interface
est utilisable immédiatement ; seule la première recherche attend que le worker affiche
`ready` dans sa fenêtre.

Pour tout arrêter : fermez les fenêtres ouvertes par `demarrer.bat`, puis
double-cliquez sur **`arreter.bat`** (coupe aussi PostgreSQL et Redis).

Ces deux scripts reproduisent exactement les commandes détaillées ci-dessous ; ils
supposent que l'installation initiale (prochaine section) a déjà été faite une fois.

### Démarrage avec Docker (recommandé pour un déploiement, pas pour le développement)

```bash
cp .env.example .env
```

Puis éditez `.env` — au minimum ces trois valeurs :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

- `CLE_SECRETE` : la valeur générée ci-dessus
- `POSTGRES_MOT_DE_PASSE` : un mot de passe solide
- `STRIPE_CLE_SECRETE` et `STRIPE_WEBHOOK_SECRET` : voir « Facturation via Stripe »
  ci-dessous (facultatif pour un premier lancement en local, sans paiement réel)

Puis lancez l'ensemble :

```bash
docker compose up -d
```

L'API démarre sur `http://localhost:8010`, applique les migrations et initialise les
paliers d'abonnement automatiquement.

- Documentation interactive de l'API : http://localhost:8010/api/docs
- Sonde de santé : http://localhost:8010/api/sante

### Installation locale (sans Docker, pour le développement)

C'est l'installation que suppose `demarrer.bat` : à faire une seule fois.

```bash
cd backend
python -m venv .venv
```

```bash
.venv/Scripts/pip install -e ".[dev]"
```

(sous Linux/macOS : `.venv/bin/pip install -e ".[dev]"`)

Lancez PostgreSQL et Redis, puis appliquez les migrations :

```bash
cd backend && alembic upgrade head && python -m app.scripts.initialiser_plans
```

Démarrez l'API :

```bash
cd backend && uvicorn app.main:app --reload
```

Et, dans deux autres terminaux, les workers :

```bash
cd backend && celery -A app.taches.celery_app worker -Q recherche -c 2 --loglevel=info
```

```bash
cd backend && celery -A app.taches.celery_app worker -Q enrichissement,pivot,maintenance -c 4 --loglevel=info
```

Sous Windows, ajoutez `--pool=solo` aux commandes Celery (le mode multiprocessus par
défaut n'y fonctionne pas) :

```bash
cd backend && celery -A app.taches.celery_app worker -Q recherche,enrichissement,pivot,maintenance --pool=solo --loglevel=info
```

### Frontend

```bash
cd frontend && npm install
```

```bash
cd frontend && npm run dev
```

L'interface est alors disponible sur http://localhost:5183. Le serveur de
développement redirige `/api` et `/ws` vers le backend sur le port 8000 : les deux
applications partagent la même origine, ce qui permet aux cookies d'authentification
de circuler sans configuration CORS supplémentaire.

Pour construire la version de production :

```bash
cd frontend && npm run build
```

Le résultat est produit dans `frontend/dist`, à servir par Caddy ou Nginx.

---

## Utilisation

### 1. Créer un compte

```bash
curl -X POST http://localhost:8010/api/v1/auth/inscription \
  -H "Content-Type: application/json" \
  -d '{"email":"vous@exemple.fr","mot_de_passe":"UnMotDePasseSolide2026","nom_organisation":"Mon cabinet","accepter_cgu":true}' \
  -c cookies.txt
```

L'acceptation des conditions d'utilisation est obligatoire : c'est la trace du
consentement au cadre légal, exigée avant toute recherche.

Depuis l'interface, rien de plus n'est demandé. **En ligne de commande, cet appel
échoue** avec « Épreuve anti-robot absente » : l'inscription exige une preuve de
calcul que le navigateur résout tout seul (voir
[Protection contre l'abus](#protection-contre-labus)). Pour créer un compte sans
navigateur — script d'amorçage, test manuel — passer `anti_abus.actif: false` dans
`backend/config.yaml`, ou utiliser l'interface.

### 2. Lancer une investigation

```bash
curl -X POST http://localhost:8010/api/v1/investigations \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"pseudo":"le_pseudo_recherche","profondeur_pivot":2,"mode_pivot":"supervise"}'
```

Les options envoyées sont **bornées côté serveur** par le plan actif : demander une
profondeur de 9 sur le palier gratuit enregistrera 0.

Pour partir de plusieurs éléments (plans payants), ajouter `points_depart`. Le champ
`type` est facultatif : omis, il est déduit de la valeur.

```bash
curl -X POST http://localhost:8010/api/v1/investigations \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"pseudo":"le_pseudo_recherche",
       "points_depart":[{"valeur":"jean.martin@exemple.fr"},
                        {"valeur":"https://github.com/jeanmartin"},
                        {"valeur":"+33612345678","type":"telephone"}]}'
```

Les types acceptés et ceux que le plan autorise se lisent sur
`GET /api/v1/investigations/types-recherche` — c'est ce que l'interface utilise pour
construire son formulaire.

### 3. Suivre la progression en temps réel

```javascript
const suivi = new WebSocket(`ws://localhost:8010/ws/investigations/${investigationId}`);
suivi.onmessage = (message) => console.log(JSON.parse(message.data));
```

Événements diffusés : `progression`, `etape`, `profil_trouve`, `noeud_ajoute`,
`pivot_propose`, `recherche_terminee`, `investigation_terminee`, `erreur`.

### 4. Consulter les résultats

```bash
curl -b cookies.txt http://localhost:8010/api/v1/investigations/ID/graphe
curl -b cookies.txt "http://localhost:8010/api/v1/investigations/ID/profils?tri=score"
curl -b cookies.txt http://localhost:8010/api/v1/investigations/ID/profils/PROFIL_ID
curl -b cookies.txt "http://localhost:8010/api/v1/investigations/ID/export?format=json" -o resultats.json
```

### 5. Arrêter une recherche en cours

```bash
curl -X POST -b cookies.txt http://localhost:8010/api/v1/investigations/ID/annuler
```

Depuis l'interface, le bouton **« Arrêter la recherche »** apparaît sous la barre de
progression. Une recherche sur la totalité des sites dure une quinzaine de minutes :
pouvoir l'interrompre évite d'attendre un résultat dont on n'a plus besoin.

L'arrêt est **coopératif** : le worker tourne en pool `solo` sous Windows, où tuer la
tâche reviendrait à tuer le service entier. Un drapeau est donc posé en base, que
chaque étape consulte à ses points de reprise. Concrètement :

- le sous-processus Maigret est arrêté **en une à deux secondes** ;
- les comptes **déjà enregistrés sont conservés** et restent exploitables (en
  revanche, un scan Maigret interrompu ne rend rien : il n'écrit son rapport qu'à la
  fin) ;
- aucun enrichissement ni rebond n'est engagé derrière ;
- le quota n'est **rendu que si la recherche n'a rien trouvé**. Rembourser une
  recherche déjà fructueuse permettrait d'enchaîner « je lance, je récupère, j'annule,
  je suis remboursé », soit un volume gratuit illimité.

### 6. Valider les pivots (mode supervisé)

```bash
curl -b cookies.txt http://localhost:8010/api/v1/investigations/ID/pivots?statut=en_attente
curl -X POST -b cookies.txt -H "Content-Type: application/json" \
  -d '{"accepter":true}' \
  http://localhost:8010/api/v1/investigations/ID/pivots/PROPOSITION_ID/decision
```

---

## Configuration

Deux fichiers, aux rôles volontairement séparés :

| Fichier | Contenu | Modification |
|---|---|---|
| `.env` | Secrets et infrastructure (mots de passe, URLs, clés API) | Jamais versionné |
| `backend/config.yaml` | Réglages métier (poids de scoring, seuils, limites de débit, rétention) | Versionné, ajustable sans redéploiement du code |

Réglages les plus utiles dans `config.yaml` :

- `correlation.regles.*.poids` — influence de chaque règle sur le score
- `correlation.seuils` — bornes des niveaux de confiance faible / moyen / élevé
- `pivot.profondeur_plafond_serveur` — plafond dur qu'aucun plan ne peut dépasser
- `rate_limiting.par_domaine` — débit autorisé vers chaque site cible
- `anti_abus.*` — protections contre la création de comptes en série (ci-dessous)
- `retention.jours_defaut` — durée de conservation des investigations (RGPD)

### Protection contre l'abus

Le palier gratuit offrant 15 recherches par mois, un script qui crée des comptes en
série obtiendrait un volume illimité. Quatre protections, toutes réglables sous
`anti_abus` dans `config.yaml`, toutes sans service tiers ni frais :

| Protection | Effet | Réglage |
|---|---|---|
| Épreuve de calcul | L'inscription exige une preuve que le navigateur calcule en ~300 ms, en arrière-plan pendant la saisie. Chaque preuve ne sert qu'une fois. | `nombre_maximal`, `validite_defi_secondes` |
| Plafond par adresse IP | Pas plus de N organisations créées par jour depuis une même connexion. Rejoindre une organisation sur invitation n'est pas concerné. | `comptes_par_ip_par_jour` |
| Limitation de débit | Borne le rythme des inscriptions, connexions et investigations par adresse IP. | `debit.*` |
| Refus des adresses jetables | Les domaines de messagerie temporaire sont écartés à l'inscription. | `app/securite/domaines_jetables.py` |

Deux points d'attention :

- **`derriere_un_proxy_de_confiance` doit rester à `false`** tant qu'aucun proxy
  (Caddy, Nginx, Traefik) n'est réellement devant l'application. À `true` sans proxy,
  n'importe qui contourne toute limitation par IP en changeant un en-tête à chaque
  requête. À `false` derrière un proxy, toutes les requêtes semblent venir de la même
  adresse et un seul utilisateur trop actif bloquerait tout le monde.
- **Redis n'est pas indispensable** : sans lui, les compteurs retombent en mémoire du
  processus. La règle reste appliquée, sa portée seule est réduite (un compteur par
  processus au lieu d'un compteur partagé).

L'ensemble se désactive d'un `anti_abus.actif: false` — utile en développement ou pour
un script d'amorçage, à ne pas laisser en production.

### Clés API recommandées

- `GITHUB_TOKEN` : fait passer la limite de 60 à 5000 requêtes par heure. Fortement
  recommandé dès que plusieurs clients utilisent le service.
- `LASTFM_API_KEY` : gratuite ([last.fm/api/account/create](https://www.last.fm/api/account/create)),
  sans laquelle le module Last.fm reste simplement inactif.
- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` : application gratuite
  ([dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps)), même principe.

---

## Facturation via Stripe

Stripe pilote l'abonnement **depuis l'application** : c'est Searcher qui crée la
session de paiement (Stripe Checkout) et la session de gestion (portail de
facturation), Stripe se contentant de notifier les changements par webhook. Il gère
la TVA européenne automatiquement (Stripe Tax).

Mise en place :

1. Créez un compte Stripe, puis un produit par palier payant (Starter, Pro,
   Entreprise) avec un prix récurrent mensuel (Produits > Ajouter un produit).
2. Renseignez la correspondance dans `.env` :
   `STRIPE_PRIX=price_xxx:starter,price_yyy:pro,price_zzz:entreprise`
   (ou directement dans la colonne `plans.stripe_price_id` en base — la colonne a
   priorité si les deux sont renseignés).
3. Créez un endpoint de webhook dans le tableau de bord Stripe (Développeurs >
   Webhooks) pointant vers `https://votre-domaine.fr/api/v1/stripe/webhook`, abonné
   au minimum à `checkout.session.completed`, `customer.subscription.updated` et
   `customer.subscription.deleted`. Copiez le secret de signature généré dans
   `STRIPE_WEBHOOK_SECRET`.
4. Renseignez `STRIPE_CLE_SECRETE` (clé API secrète, Développeurs > Clés API).

**En développement local**, sans clé Stripe configurée, les boutons « Souscrire » et
« Ouvrir le portail de facturation » répondent une erreur claire (503) plutôt que de
planter : le reste de l'application (recherche, corrélation, quotas gratuits) reste
utilisable. Pour tester le paiement en local, le CLI Stripe (`stripe listen --forward-to
localhost:8010/api/v1/stripe/webhook`) relaie les webhooks sans exposer la machine sur
internet.

L'abonnement ne s'active qu'à réception du webhook `checkout.session.completed`, une
fois le paiement effectivement confirmé par Stripe — jamais à l'appel de
`/abonnement/checkout`, qui ne fait que créer la session de paiement.

---

## Déploiement sur VPS européen (OVH, Scaleway, Hetzner)

Configuration recommandée pour démarrer : **4 vCPU, 8 Go de RAM, 80 Go de disque**
(environ 20 à 30 €/mois). Le facteur limitant est Maigret, qui ouvre de nombreuses
connexions simultanées.

```bash
# Sur le serveur
git clone <votre-depot> searcher && cd searcher
cp .env.example .env    # renseignez les secrets de production
docker compose up -d
```

Points à ne pas négliger :

1. **`ENVIRONNEMENT=production`** dans `.env` : active le drapeau `secure` sur les cookies.
2. **Reverse proxy HTTPS obligatoire** (Caddy ou Nginx). Sans TLS, les cookies d'authentification circulent en clair.
3. **Ne jamais exposer PostgreSQL ni Redis sur internet** — le `docker-compose.yml` les lie déjà à `127.0.0.1`.
4. **Sauvegardes** : `docker exec searcher-postgres-1 pg_dump -U searcher searcher | gzip > sauvegarde.sql.gz`
5. **Hébergement en UE** : maintient les données de clients européens dans l'Union, ce qui simplifie considérablement la conformité RGPD.

Exemple de configuration Caddy (HTTPS automatique) :

```
votre-domaine.fr {
    reverse_proxy /api/* localhost:8010
    reverse_proxy /ws/*  localhost:8010
    reverse_proxy /*     localhost:5183
}
```

---

## Tests

```bash
cd backend && pytest -q
```

235 tests couvrent le moteur de corrélation, les modules de site, les chercheurs et
points de départ multiples, les sources complémentaires (recherche web et dark web),
les quotas et le gating par plan, l'isolation entre organisations, et le cycle complet
d'investigation.
Aucun n'exige de réseau, de PostgreSQL ni de Redis : ils tournent sur SQLite avec un
Maigret simulé.

Les tests les plus importants à ne jamais laisser échouer :

- `test_isolation_multitenant.py` — une fuite entre clients exposerait les
  investigations d'un cabinet à un concurrent ;
- `test_plans_et_quotas.py` — un contournement permettrait d'utiliser gratuitement les
  fonctionnalités payantes ;
- `test_correlation.py` — une régression produirait des conclusions fausses sur des
  personnes réelles.

---

## Documentation complémentaire

- [Architecture détaillée](docs/architecture.md) — structure du code, schéma de données, flux d'une investigation
- [Ajouter un module de site](docs/ajouter-un-module.md) — guide pas à pas
- [Conformité RGPD](docs/rgpd.md) — rétention, journalisation, droits des personnes
- [Licences des dépendances](THIRD_PARTY_LICENSES.md) — audit juridique avant mise sur le marché

---

## État du projet

**Application complète et vérifiée de bout en bout** (235 tests automatisés, migration
validée sur PostgreSQL 16).

### Campagne d'évaluation du 02/08/2026

Sept investigations réelles couvrant les cinq types de recherche, le multi-critères, le
rebond et les deux paliers extrêmes, suivies d'une vérification **manuelle** des URL
remontées (code HTTP *et* contenu de la page).

| Constat | Suite donnée |
|---|---|
| Départ depuis un compte connu : le pseudonyme de référence était l'URL entière, tous les scores s'effondraient (GitHub à **0 %**) | Corrigé — `pseudos_reference()` déduit le pseudonyme du type de point de départ. GitHub remonte à 88 % |
| `coherence_temporelle` (tolérance 3 ans) comptait comme second signal et hissait n'importe quel homonyme à 85 % | Corrigé — attribut `compte_pour_plafond`, la règle ne lève plus le plafond |
| 73 % des comptes remontés existent vraiment, mais appartiennent à des **homonymes** ; aucune règle ne savait dire non | Nouvelle règle `identite_contradictoire` (seule règle à score négatif) |
| Comptes pornographiques présentés à 65 %, « confiance moyenne », sur un simple pseudonyme | Plafonnés en confiance faible sans corroboration indépendante |
| 119 des 123 résultats affichés au même rang, tous à 65 % | Repliés derrière « *N* comptes au pseudonyme identique, non vérifiés » |
| Palier gratuit : 84 résultats, 0 en confiance élevée — il démontrait l'inverse de ce qu'il vend | Refondu : moins de volume, mais enrichissement et 1 rebond |
| « Accès API » vendu au palier Entreprise alors que rien ne l'implémente | Retiré de la grille et de la page Abonnement |

Effet mesuré sur la recherche « torvalds » (500 sites) : la liste exploitable passe de
**123 comptes indifférenciés à 5**. Les homonymes vérifiés à la main retombent de
« confiance moyenne » à 23–43 % (Instagram/« Marco Migozzi » 43 %, Steam/« WTF Gaming »
23 %), tandis que GitHub et GitHubGist conservent 78 % sur trois signaux réels.

Parcours antérieur, exécuté le 29/07/2026 avec Maigret sur de vrais pseudonymes :

| Étape vérifiée | Résultat observé |
|---|---|
| Inscription, acceptation des CGU, session par cookie | ✅ |
| Recherche « torvalds » sur 50 sites | 26 comptes trouvés, 4 à confiance élevée |
| Corrélation et plafonnement du score | GitHub 90 %, comptes à signal unique plafonnés à 65 % |
| Enrichissement GitHub | 7 informations extraites, avatar identifié par hash perceptuel |
| Rebond automatique sur « soxoj » | variante `sox0j` détectée, explorée, puis arrêt propre |
| Graphe | 31 nœuds, 34 arêtes, couleurs et tailles selon le score |
| Explication du score dans l'interface | contribution détaillée de chaque règle |
| Exports JSON, CSV et PDF | ✅ |
| Quotas et gating par plan | consommation exacte, options bornées selon le palier |
| Double authentification (TOTP) | activation, connexion, codes de secours |
| Paiement Stripe | Checkout, portail client, webhooks (voir « Facturation via Stripe ») |

Restent à faire :

- envoi des courriels d'invitation (le lien est pour l'instant affiché à l'écran) ;
- créer le compte Stripe et ses prix en production (le code est prêt, voir
  « Facturation via Stripe » ci-dessus) ;
- **volet juridique avant commercialisation** : base légale, AIPD, contrat de
  sous-traitance client — voir [docs/rgpd.md](docs/rgpd.md).

### Limites connues, mesurées et non résolues

À garder en tête avant toute démonstration commerciale — ce sont des limites de
conception, pas des bogues :

- **Le score est une moyenne pondérée**, donc un compte à trois signaux peut passer
  *sous* un compte à deux signaux plus francs : sur « torvalds », GitHub (78 %, trois
  signaux dont l'avatar) se classe derrière Snapchat (82 %, deux signaux). Corriger
  suppose de revoir l'agrégation elle-même, pas d'ajouter une règle.
- **Les homonymes de la même famille sont indétectables** : « Patricia Torvalds » et
  « Patrick Torvalds » partagent légitimement le patronyme de la cible et remontent
  donc en confiance élevée. C'est arguablement le bon comportement — ce sont les
  comptes qu'un analyste doit examiner en premier — mais ce ne sont pas la cible.
- **Quatre faux positifs structurels de Maigret** subsistent, où la « page de profil »
  est une page générique sans identifiant : `discord.com`, `bit.ly`, `bitbucket.org`,
  `donationalerts.com`. À traiter par une liste de domaines, comme `site_douteux`.
- **Environ 18 % des comptes remontés sont invérifiables** automatiquement : le site
  répond derrière un pare-feu anti-robot (Cloudflare « Just a moment… »). Ni l'outil ni
  l'analyste ne peuvent conclure sans ouvrir la page à la main.
- **La couverture des modules reste marginale** : 22 modules pour ~3200 sites, soit
  moins de 10 % des résultats enrichis sur une recherche large. L'essentiel du corpus
  reste des URL nues.

## Crédits

Ce produit s'appuie sur [Maigret](https://github.com/soxoj/maigret) (MIT,
© 2020 Soxoj) pour la recherche de pseudonymes. Voir
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) pour l'ensemble des dépendances.
