# Ops — recherche et corrélation de pseudonymes (OSINT)

[![Licence MIT](https://img.shields.io/badge/licence-MIT-green.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![React 18](https://img.shields.io/badge/interface-React%2018-blue.svg)
![Docker Compose](https://img.shields.io/badge/d%C3%A9ploiement-Docker%20Compose-blue.svg)
![Sources publiques](https://img.shields.io/badge/sources-publiques%20uniquement-lightgrey.svg)

Application web autohébergée : recherche d'un pseudonyme sur ~3200 sites, corrélation
des comptes trouvés vers une même personne, enrichissement par API publiques, et
restitution en graphe de relations avec un score explicable.

Instance locale ou serveur, au choix de l'opérateur : aucun service tiers n'intervient
dans la chaîne, aucune donnée d'investigation ne sort de l'installation. Sources
publiques uniquement — ni carnet d'adresses aspiré, ni base de fuites, ni session
authentifiée sur un site tiers.

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
> Si vous exploitez cet outil dans un cadre professionnel, faites valider par un
> juriste votre base légale de traitement (intérêt légitime) et réalisez une analyse
> d'impact (AIPD) — voir [docs/rgpd.md](docs/rgpd.md).

---

**Installation en une commande** : [Docker](#docker--installation-complète), puis
l'interface sur `http://localhost:8080`.

| | |
|---|---|
| [Ce que fait l'outil](#ce-que-fait-loutil) | la chaîne complète, et ce qu'elle ne sait pas faire |
| [Ce dont dispose une instance](#ce-dont-dispose-une-instance) | aucun quota, aucune fonctionnalité réservée |
| [Installation](#installation) | Docker, lanceur Windows, ou installation locale |
| [Utilisation](#utilisation) | créer un compte, lancer et suivre une investigation, exporter |
| [Configuration](#configuration) | réglages métier, protection contre l'abus, clés d'API |
| [Instance sur serveur](#instance-sur-serveur) | accès distant, HTTPS, sauvegardes |
| [Tests](#tests) | 255 tests, ce qu'ils couvrent |
| [État du projet](#état-du-projet) | mesures de terrain et limites connues |
| [Contribuer](#contribuer) | ajouter un module de site |

---

## Ce que fait l'outil

1. **Recherche** — lance [Maigret](https://github.com/soxoj/maigret) sur un pseudonyme et récupère les comptes trouvés, complété par une recherche web ouverte (DuckDuckGo) et une recherche dans l'index public du réseau Tor (Ahmia — jamais de connexion Tor depuis le serveur, voir [`backend/app/moteur/sources/`](backend/app/moteur/sources/)). Une investigation peut aussi partir de plusieurs éléments à la fois : adresse électronique, numéro de téléphone, adresse d'un compte connu, adresse postale. Le type de chaque élément saisi est **deviné automatiquement**, et reste modifiable.
2. **Corrèle** — attribue à chaque compte un score de confiance calculé par des règles pondérées (similarité du pseudonyme, avatar identique, adresse partagée, liens réciproques, cohérence des dates), et écarte les faux positifs.
3. **Enrichit** — applique un module par site pour extraire biographie, avatar, localisation, liens, date de création, autres pseudonymes. Vingt-deux sites couverts : GitHub, GitLab, Codeberg, Gitee, Reddit, Mastodon, Pixelfed, PeerTube, Lemmy, Bluesky, Hacker News, Dev.to, Keybase, MixCloud, Steam, Lobsters, Wikipédia, Liberapay, Goodreads, Letterboxd, Last.fm, Twitch (ces deux derniers nécessitent une clé API gratuite).
4. **Pivote** — repart automatiquement des informations découvertes (un pseudonyme dans une bio relance une recherche, un lien déclenche un enrichissement direct), dans la limite de la profondeur autorisée.
5. **Visualise** — restitue le tout en graphe interactif : nœuds = identités et informations, arêtes = relations découvertes.

### Téléphone et adresse : ce qu'on peut en tirer, et ce qu'on ne peut pas

Ces deux recherches ne fonctionnent pas comme celle par pseudonyme, et la différence
doit être posée d'emblée.

**Ce qui est structurellement impossible.** `libphonenumber` ne lit que des plages
d'attribution : pays, région, type de ligne, et opérateur — *uniquement sur mobile*, un
fixe n'en renvoie aucun. Cet opérateur est celui du **bloc d'attribution d'origine** :
avec la portabilité, un numéro passé de SFR à Free affichera toujours SFR. À ne jamais
présenter comme un fait. Surtout, **rien de public ne relie un numéro à une personne
privée** : les outils qui le prétendent s'appuient sur des carnets d'adresses aspirés
(Truecaller, GetContact), des bases de fuites ou l'énumération des messageries — tous
exclus par le parti pris « APIs publiques gratuites uniquement ».

**Ce que l'outil fait, désormais.** Quand le numéro est professionnel ou
institutionnel, la réponse est écrite dans les pages qui le citent. L'outil les
exploite au lieu de se contenter de les lister :

- le **nom de l'entité** est retenu s'il concorde sur **au moins deux domaines
  distincts** — un titre isolé peut dire n'importe quoi, deux sites indépendants se
  corroborent ;
- l'**adresse postale** est reconnue à sa forme française dans les extraits.

Mesuré sur le standard du Louvre (`+33140205050`) : l'outil rendait huit liens et rien
d'autre, alors que le nom figurait dans six titres sur huit et l'adresse dans un
extrait. Il produit maintenant `entreprise = « Musée Du Louvre »` et
`localisation = « 34 quai François Mitterrand 75001 Paris »`, exploitables par la
corrélation et le rebond. Même chose par adresse : `55 rue du Faubourg Saint-Honoré`
donne `entreprise = « Palais de l'Élysée »`.

Les pages sans contenu propre sont écartées sur **deux critères** : une liste de
domaines (annuaires inversés, cartographie, estimation immobilière) et, parce qu'une
liste est toujours en retard sur le web, la présence de formulations creuses
(« à qui appartient ce numéro ? », « nombre d'opinions »). Voir
[`backend/app/moteur/chercheurs/mentions.py`](backend/app/moteur/chercheurs/mentions.py).

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
qu'il en trouve **appartenant à d'autres personnes** : sur les trois comptes
homonymes vérifiés, le profil déclare à chaque fois un nom différent — un nom sans
rapport, un patronyme voisin, un pseudonyme de joueur — et l'un d'eux est domicilié
sur un autre continent.

Le moteur exploite désormais ces noms au lieu de les ignorer. Trois précautions, toutes
tirées de cas réels mesurés :

- deux comptes portant le **même nom étranger** au pseudonyme ne se corroborent pas :
  Instagram et Pinterest déclaraient tous deux « Paolo Ferrante » — c'est l'indice qu'un
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

## Ce dont dispose une instance

Par défaut (`MODE_AUTOHEBERGE=true`), toute organisation reçoit le palier **« Libre »** :
aucun quota, aucune fonctionnalité réservée.

| | Inclus |
|---|---|
| Recherches par mois | sans limite |
| Sites analysés par recherche | toute la base de Maigret (~3200) |
| Types de recherche | pseudonyme, adresse électronique, téléphone, adresse postale, compte connu, multi-critères |
| Rebond (pivot) | jusqu'à 10 niveaux, supervisé ou automatique |
| Modules d'enrichissement | les 22 modules |
| Recherche web et dark web | incluse |
| Résultats de sites sensibles | inclus |
| Exports | JSON, CSV, PDF |
| Utilisateurs et organisations | sans limite |

Les seules bornes restantes sont celles du serveur, dans
[`backend/config.yaml`](backend/config.yaml) : débit par domaine interrogé, et plafond
dur de profondeur de rebond. Elles protègent les sites cibles et la machine, pas l'usage.

Les **sites à caractère sexuel** sont inclus, mais un tel compte reste en **confiance
faible** tant qu'il ne repose que sur un pseudonyme identique : l'imputer sur cette
seule base serait diffamatoire, et constituerait un traitement de données de
l'article 9 fondé sur un faux positif. Voir
[`backend/app/moteur/sites_sensibles.py`](backend/app/moteur/sites_sensibles.py).

> **Accès API machine à machine : pas construit.** Le code de fonctionnalité
> (`API_PUBLIQUE`) existe mais rien ne le vérifie — ni clé, ni authentification
> machine. L'API REST s'utilise avec un cookie de session (voir « Utilisation »).
> État des lieux : [docs/acces-api.md](docs/acces-api.md).

### Ouvrir une instance à des tiers

Le code conserve de sa conception initiale un système de paliers, de quotas et de
facturation Stripe. Il est inerte en autohébergement. `MODE_AUTOHEBERGE=false` rétablit
les paliers définis dans
[`backend/app/facturation/plans.py`](backend/app/facturation/plans.py) ; le branchement
Stripe est décrit plus bas. Les gardes s'appliquent côté serveur, endpoints **et**
tâches de fond — jamais par masquage d'un bouton.

---

## Installation

### Prérequis

- **Docker et Docker Compose** : seule dépendance de l'installation complète
- ou, pour développer sans conteneuriser l'application : Python 3.11+, Node 20+,
  PostgreSQL 16 et Redis 7
- 2 Go de RAM minimum, 4 Go recommandés (Maigret est gourmand pendant les scans)

### Docker : installation complète

La voie recommandée, et la seule qui livre tout d'un bloc — base, cache, API, workers,
planificateur et interface web. Aucune dépendance Python ou Node à installer sur la
machine.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Deux valeurs à renseigner dans `.env`, et rien d'autre :

- `CLE_SECRETE` : la valeur générée ci-dessus. L'application refuse de démarrer en
  production tant qu'elle vaut celle d'exemple, qui est publique ;
- `POSTGRES_MOT_DE_PASSE` : au choix, il ne sert qu'entre les conteneurs.

Les clés de Stripe et des modules de site restent vides : elles sont facultatives
(voir « Clés d'API des modules »).

```bash
docker compose up -d
```

Migrations de schéma et initialisation des paliers sont appliquées au démarrage de
l'API, sans intervention.

| | Adresse |
|---|---|
| Interface | http://localhost:8080 |
| Documentation interactive de l'API | http://localhost:8010/api/docs |
| Sonde de santé | http://localhost:8010/api/sante |

L'interface relaie elle-même `/api` et `/ws` vers l'API, sur la même origine : un seul
port à ouvrir, et aucun CORS à configurer. L'API n'est publiée que sur `127.0.0.1`,
pour consulter sa documentation depuis la machine hôte.

Deux conséquences de cette topologie :

- nginx étant devant l'API, toutes les requêtes lui parviennent avec l'adresse du
  conteneur. Pour que le plafond par adresse IP et la limitation de débit distinguent
  les utilisateurs, passez `anti_abus.derriere_un_proxy_de_confiance` à `true` dans
  [`backend/config.yaml`](backend/config.yaml) — fiable ici, puisque l'API n'est pas
  joignable directement depuis l'extérieur. Sans objet sur une instance personnelle.
- `backend/config.yaml` est monté en lecture seule dans les conteneurs : un réglage
  métier s'applique au redémarrage des services, sans reconstruire les images.

En HTTP, laissez `ENVIRONNEMENT=developpement` : en `production`, les cookies
d'authentification portent le drapeau `secure` et exigent HTTPS (voir « Instance sur
serveur »).

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
développement redirige `/api` et `/ws` vers le backend sur le port 8010 : les deux
applications partagent la même origine, ce qui permet aux cookies d'authentification
de circuler sans configuration CORS supplémentaire.

Pour construire la version de production :

```bash
cd frontend && npm run build
```

Le résultat est produit dans `frontend/dist`, à servir par n'importe quel serveur
web. L'installation Docker s'en charge : son image `web` compile l'interface puis la
sert derrière nginx, qui relaie aussi l'API.

---

## Utilisation

### 1. Créer un compte

```bash
curl -X POST http://localhost:8010/api/v1/auth/inscription \
  -H "Content-Type: application/json" \
  -d '{"email":"vous@exemple.fr","mot_de_passe":"UnMotDePasseSolide2026","nom_organisation":"Mon cabinet","accepter_cgu":true}' \
  -c cookies.txt
```

L'acceptation du cadre d'utilisation est obligatoire : c'est la trace du consentement,
exigée avant toute recherche.

Depuis l'interface (http://localhost:8080), rien de plus n'est demandé. **L'appel direct
ci-dessus échoue** avec « Épreuve anti-robot absente » : l'inscription exige une preuve
de calcul que le navigateur résout de lui-même (voir
[Protection contre l'abus](#protection-contre-labus)).

Pour amorcer une installation neuve, ou provisionner un compte sans ouvrir de
navigateur :

```bash
docker compose exec api python -m app.scripts.creer_compte \
  --email vous@exemple.fr --organisation "Mon cabinet" --accepter-cadre-legal
```

Sans Docker, depuis `backend/` : `.venv/Scripts/python -m app.scripts.creer_compte` avec
les mêmes options. Le mot de passe est demandé en saisie masquée ; l'option
`--mot-de-passe` existe pour les scripts, mais laisse le secret dans l'historique du
terminal. Le compte créé est administrateur de son organisation.

Cette commande court-circuite l'épreuve de calcul et le plafond par adresse IP — et
seulement eux : politique de mot de passe, unicité de l'adresse et journalisation du
consentement restent appliquées à l'identique. Il n'y a donc jamais lieu de désactiver
`anti_abus` pour créer un compte.

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

Ces protections ne servent que si votre instance est **ouverte sur internet** : elles
empêchent un inconnu d'y créer des comptes en série pour consommer votre bande passante
et faire bannir votre adresse IP par les sites interrogés. Sur une instance purement
locale, elles sont sans objet. Quatre protections, toutes réglables sous `anti_abus`
dans `config.yaml`, toutes sans service tiers ni frais :

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

### Clés d'API des modules

Toutes facultatives, toutes gratuites, toutes dans le `.env` de l'instance — le dépôt
n'en contient aucune. Un module privé de sa clé s'abstient sans faire échouer la
recherche.

| Variable | Source | Effet de son absence |
|---|---|---|
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens), jeton classique sans aucune portée cochée | 60 requêtes/heure au lieu de 5000 — la seule qui compte réellement sur une recherche large |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), application de type *script* | Reddit interrogé sans authentification, débit plus faible |
| `LASTFM_API_KEY` | [last.fm/api/account/create](https://www.last.fm/api/account/create) | module Last.fm inactif |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) | module Twitch inactif |

Le `.env` est relu au démarrage : redémarrer l'API et les workers après modification.
Le journal de démarrage indique le nombre de modules chargés.

---

## Facturation par Stripe (uniquement si vous ouvrez un service)

> Inutile pour une installation personnelle : en mode autohébergé, rien de cette
> section n'est à configurer. Elle ne concerne que `MODE_AUTOHEBERGE=false`.

Stripe pilote l'abonnement **depuis l'application** : c'est Ops qui crée la
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

## Instance sur serveur

Pertinent pour un accès à distance ou un usage d'équipe ; superflu pour une instance
locale. Dimensionnement suffisant : **4 vCPU, 8 Go de RAM, 80 Go de disque**. Le facteur
limitant est Maigret, qui ouvre un grand nombre de connexions simultanées.

```bash
# Sur le serveur
git clone https://github.com/<votre-compte>/ops.git ops && cd ops
cp .env.example .env    # renseignez CLE_SECRETE et POSTGRES_MOT_DE_PASSE
docker compose up -d
```

Exigences de mise en production :

1. **`ENVIRONNEMENT=production`** dans `.env` : active le drapeau `secure` sur les cookies.
2. **Reverse proxy HTTPS obligatoire** (Caddy ou Nginx). Sans TLS, les cookies d'authentification circulent en clair.
3. **Ne jamais exposer PostgreSQL ni Redis sur internet** — le `docker-compose.yml` les lie déjà à `127.0.0.1`.
4. **Sauvegardes** : `docker exec ops-postgres-1 pg_dump -U searcher searcher | gzip > sauvegarde.sql.gz` (le nom du conteneur dépend du dossier de clonage : `docker ps` le donne)
5. **Hébergeur européen** : maintient les données dans l'Union, ce qui simplifie considérablement la conformité RGPD (voir [docs/rgpd.md](docs/rgpd.md)).

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

240 tests couvrent le moteur de corrélation, les modules de site, les chercheurs et
points de départ multiples, les sources complémentaires (recherche web et dark web),
les quotas et le gating par plan, l'isolation entre organisations, et le cycle complet
d'investigation.
Aucun n'exige de réseau, de PostgreSQL ni de Redis : ils tournent sur SQLite avec un
Maigret simulé.

Les tests les plus importants à ne jamais laisser échouer :

- `test_isolation_multitenant.py` — une fuite entre organisations exposerait les
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
- [Licences des dépendances](THIRD_PARTY_LICENSES.md) — toutes permissives (MIT, BSD, Apache)

---

## État du projet

**Application complète et vérifiée de bout en bout** (245 tests automatisés, migration
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
| Palier par défaut : 84 résultats, aucun en confiance élevée — la corrélation ne se distinguait pas d'une liste brute | Enrichissement et premier niveau de rebond ouverts par défaut |
| « Accès API » annoncé alors que rien ne l'implémente | Retiré de la grille et de la page Abonnement |

Effet mesuré sur la recherche « torvalds » (500 sites) : la liste exploitable passe de
**123 comptes indifférenciés à 5**. Les homonymes vérifiés à la main retombent de
« confiance moyenne » à 23–43 % (Instagram/« Paolo Ferrante » 43 %, Steam/« Nightfall Gaming »
23 %), tandis que GitHub et GitHubGist conservent 78 % sur trois signaux réels.

Parcours antérieur, exécuté le 29/07/2026 avec Maigret sur de vrais pseudonymes :

| Étape vérifiée | Résultat observé |
|---|---|
| Inscription, acceptation du cadre légal, session par cookie | ✅ |
| Recherche « torvalds » sur 50 sites | 26 comptes trouvés, 4 à confiance élevée |
| Corrélation et plafonnement du score | GitHub 90 %, comptes à signal unique plafonnés à 65 % |
| Enrichissement GitHub | 7 informations extraites, avatar identifié par hash perceptuel |
| Rebond automatique sur « soxoj » | variante `sox0j` détectée, explorée, puis arrêt propre |
| Graphe | 31 nœuds, 34 arêtes, couleurs et tailles selon le score |
| Explication du score dans l'interface | contribution détaillée de chaque règle |
| Exports JSON, CSV et PDF | ✅ |
| Quotas et gating par plan | consommation exacte, options bornées selon le palier |
| Double authentification (TOTP) | activation, connexion, codes de secours |
| Paiement Stripe (mode service seulement) | Checkout, portail client, webhooks |

Restent à faire :

- envoi des courriels d'invitation : le lien d'invitation s'affiche à l'écran, il faut
  le transmettre à la main (aucun serveur de courriel n'est requis pour le reste) ;
- enrichissement de la couverture des modules (22 sites sur ~3200, voir les limites
  ci-dessous et [docs/feuille-de-route.md](docs/feuille-de-route.md)).

### Limites connues, mesurées et non résolues

À garder en tête avant d'exploiter un résultat — ce sont des limites de conception,
pas des bogues :

- **Le score est une moyenne pondérée**, donc un compte à trois signaux peut passer
  *sous* un compte à deux signaux plus francs : sur « torvalds », GitHub (78 %, trois
  signaux dont l'avatar) se classe derrière Snapchat (82 %, deux signaux). Corriger
  suppose de revoir l'agrégation elle-même, pas d'ajouter une règle.
- **Les homonymes de la même famille sont indétectables** : « Pauline Torvalds » et
  « Paul Torvalds » partagent légitimement le patronyme de la cible et remontent
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

## Licence

[MIT](LICENSE) : usage, modification et redistribution libres, y compris en contexte
commercial, mention de copyright conservée. Logiciel fourni sans garantie — la légalité
de l'usage incombe à l'opérateur de l'instance (voir le cadre légal en tête de fichier).

## Contribuer

Les **modules de site** sont la contribution la plus utile : un fichier d'une centaine
de lignes, procédure dans [docs/ajouter-un-module.md](docs/ajouter-un-module.md).

```bash
cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check .
cd ../frontend && npm run build
```

Deux exigences non négociables :

- **aucune donnée réelle dans le dépôt** — ni identifiant, ni jeton, ni résultat
  nominatif, ni capture d'une personne identifiable ; les tests travaillent sur des
  vecteurs fabriqués ;
- **sources publiques uniquement** — pas de module exigeant une session authentifiée
  sur un site tiers, pas de contournement de protection, pas de base de fuites.

## Crédits

Ops s'appuie sur [Maigret](https://github.com/soxoj/maigret) (MIT,
© 2020 Soxoj) pour la recherche de pseudonymes. Voir
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) pour l'ensemble des dépendances.
