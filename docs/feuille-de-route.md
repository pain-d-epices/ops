# Feuille de route

Plan établi le 29/07/2026, à valider avant mise en œuvre. Rien de ce document n'est
encore développé.

Trois axes, dans l'ordre où je les recommande :

1. **Élargir la couverture des modules** — le facteur limitant mesuré aujourd'hui
2. **Points de départ multiples** (fonctionnalité payante demandée)
3. **Nouveaux types de recherche** : e-mail, téléphone, adresse

---

## Préalable : la vérité sur Osintgram et les plateformes fermées

Ce point conditionne tout le reste, donc il vient en premier.

### Osintgram n'est pas intégrable

| Obstacle | Détail |
|---|---|
| **Licence GPL-3.0** | Intégrer ce code dans Ops contaminerait juridiquement le produit. En SaaS pur (le code n'est jamais distribué), la GPL-3.0 ne force pas la publication — c'est l'AGPL qui couvre ce cas. Mais la position est fragile, et interdit toute installation chez un client. |
| **Compte Instagram réel obligatoire** | L'outil se connecte avec de vrais identifiants. Chaque client devrait fournir les siens, ou vous exposeriez les vôtres. |
| **Violation des conditions d'Instagram** | Le scraping authentifié est explicitement interdit. Bannissement du compte à la clé, et exposition juridique de qui opère l'instance. |
| **Fiabilité** | L'outil casse à chaque changement de Meta, ce qui arrive plusieurs fois par an. |

**Ce qui reste possible sur Instagram** : l'API Graph officielle, qui exige un compte
Business et une validation par Meta, et ne donne accès qu'à des comptes professionnels
ayant consenti. Utile pour de la veille de marque, pas pour une investigation.

### Les autres grandes plateformes

| Plateforme | Voie légale | Coût | Verdict |
|---|---|---|---|
| **X / Twitter** | API officielle v2 | ~200 $/mois (palier Basic) | **Écarté** — outil payant : le projet n'en intègre aucun. |
| **Discord** | API officielle avec jeton de bot | Gratuit | **Réaliste mais limité** — voir ci-dessous |
| **Instagram** | API Graph (comptes Business uniquement) | Gratuit | Peu utile en investigation |
| **TikTok** | API Research | Réservée aux chercheurs universitaires | Hors de portée |
| **LinkedIn** | Aucune API de consultation de profils | — | À écarter : le scraping y est poursuivi activement |
| **Facebook** | Aucune | — | À écarter |

### Le cas Discord, précisément

Discord ne permet pas de **trouver** quelqu'un par pseudonyme : les pseudos n'y sont
pas énumérables publiquement, c'est une décision de conception de leur part.

En revanche, avec un jeton de bot (gratuit), l'API officielle donne le profil complet
à partir d'un **identifiant numérique** : nom d'utilisateur, avatar, bannière, date de
création du compte, badges.

Conséquence concrète : un module Discord est utile **en pivot** (quand une autre source
a livré l'identifiant), jamais en découverte initiale. C'est exactement le genre de cas
que l'axe 3 rendra exploitable.

---

## Axe 1 — Élargir la couverture des modules

**Constat mesuré** : sur une investigation de 109 comptes, 2 seulement relevaient d'un
site couvert. La couverture est le vrai facteur limitant, pas le moteur.

### Vague A — APIs publiques, sans clé (effort faible, aucun risque)

Chaque module suit le patron existant : environ une heure de travail et un test.

| Site | Intérêt | État |
|---|---|---|
| Lobsters, Codeberg | communautés techniques, profils riches | ✅ fait |
| SourceHut | idem | écarté — pas d'API de lecture anonyme (GraphQL sous OAuth uniquement) |
| Last.fm | API publique avec clé gratuite, historique d'écoute et localisation | ✅ fait |
| Wikipédia / Wikimedia | contributions publiques, très révélatrices d'intérêts et de fuseau horaire | ✅ fait |
| Telegram (canaux publics) | via l'API Bot, sur canaux publics uniquement | écarté — l'API Bot ne consulte que des canaux, pas un compte individuel |
| Twitch | API officielle, clé gratuite | ✅ fait |
| Pixelfed, PeerTube, Lemmy | fédivers : mêmes API que Mastodon, quasi gratuit à ajouter | ✅ fait |
| Ko-fi | financement participatif, souvent lié à une identité réelle | écarté — aucun point d'accès public en lecture |
| Liberapay | idem | ✅ fait (apport modeste : pas de biographie exposée par l'API) |
| Goodreads, Letterboxd | via flux RSS publics quand l'API manque | ✅ fait |

### Vague B — Clé API gratuite (effort faible, configuration client)

Steam *(fait via XML)*, Twitch *(fait)*, Last.fm *(fait)*, Discord (jeton de bot),
YouTube (quota gratuit). Chacune demande une clé à configurer dans `.env` : à
documenter clairement, puisque vous n'êtes pas développeur.

### Vague C — X / Twitter via l'API officielle : écarté

~200 $/mois, seule voie propre vers X. **Écarté définitivement** : le projet refuse
tout outil tiers payant, quel que soit le rapport valeur/prix.

### Ce que je recommande d'écarter

Instagram, Facebook, LinkedIn, TikTok par scraping. Le rapport risque/bénéfice est
mauvais : bannissements, casse permanente, exposition juridique de l'opérateur.

### Vague D — Outils spécialisés existants, évalués par licence

Recherche faite sur les outils de scraping/OSINT gratuits, sans jeton ni quota payant,
spécialisés par réseau. Triés par ce qui est réellement intégrable.

**Intégrables sans réserve (licence permissive)**

| Outil | Ce qu'il fait | Licence | Verdict |
|---|---|---|---|
| [`user-scanner`](https://github.com/kaifcodec/user-scanner) | Présence e-mail/pseudo sur ~360 sites combinés | **MIT** | À intégrer — voir ci-dessus, résout le problème holehe |
| [Sherlock](https://github.com/sherlock-project/sherlock) | Recherche de pseudo sur 400+ sites, sans clé | **MIT** | Recoupe largement Maigret (déjà ~3000 sites) ; utile surtout comme validation croisée, pas prioritaire |
| `libphonenumber` (Google) | Validation et métadonnées de numéros | **Apache 2.0** | À intégrer, aucun frein |

**Fonctionnels mais à écarter ou réimplémenter (copyleft fort)**

| Outil | Ce qu'il fait | Licence | Verdict |
|---|---|---|---|
| [Blackbird](https://github.com/p1ngul1n0/blackbird) | Pseudo/e-mail sur 600+ sites via le jeu de données WhatsMyName | à vérifier au cas par cas selon le fork | Le jeu de données sous-jacent ([WhatsMyName](https://github.com/WebBreacher/WhatsMyName)) est en **CC BY-SA 4.0** — une base de données, pas du code : exploitable directement à condition de créditer la source. Piste intéressante pour élargir la couverture de vérification d'existence, indépendamment de Blackbird lui-même. |
| [Holehe](https://github.com/megadose/holehe) | Ancêtre de `user-scanner`, mêmes limites | GPL-3.0 | **Abandonné au profit de `user-scanner`** |
| [Social-Analyzer](https://github.com/qeeqbox/social-analyzer) | Recherche multi-réseaux avec score de confiance | **AGPL-3.0** | À écarter pour un SaaS : l'AGPL impose de publier le code en cas d'usage réseau |
| [GHunt](https://github.com/mxrch/GHunt) | Investigation de comptes Google (Gmail, Calendar, Maps, Photos publiques) | **AGPL-3.0** | Même obstacle. Potentiellement très utile (déduit énormément d'un simple Gmail), mais nécessiterait soit une réimplémentation MIT-safe, soit d'accepter les obligations AGPL |
| [Toutatis](https://github.com/megadose/toutatis) | Extraction e-mail/téléphone depuis un compte Instagram | GPL-3.0 | **Même risque que Osintgram** : nécessite une session Instagram authentifiée, viole les CGU d'Instagram, bannissement à la clé. Écarté pour la même raison, licence à part. |
| [PhoneInfoga](https://github.com/sundowndev/phoneinfoga) | OSINT téléphone (VoIP, opérateur) | GPL-3.0, **non maintenu** | Écarté : licence et projet à l'arrêt |

**À trancher avec vous** : GHunt (AGPL) serait le gain de valeur le plus spectaculaire
sur un simple e-mail Gmail — mais l'AGPL est la licence la plus contraignante qui
existe pour un service en ligne. L'intégrer tel quel obligerait à publier tout le code
de Ops. La seule voie propre serait de réimplémenter son approche (API Google
publiques, sans le code de GHunt) — un chantier à part entière, pas une simple
« Vague ».

---

## Axe 2 — Points de départ multiples (fonctionnalité payante)

Aujourd'hui, une investigation démarre avec **un pseudonyme, et rien d'autre**.

### Ce qui change pour l'utilisateur

Le formulaire accepte plusieurs points de départ, de types différents :

- un pseudonyme (comme aujourd'hui)
- **l'adresse d'un compte** (`https://github.com/quelquun`) — le site est enrichi
  directement, et le pseudonyme qui en est extrait lance la recherche large
- une adresse e-mail
- un numéro de téléphone
- un nom réel
- un domaine

Plusieurs éléments peuvent être fournis ensemble : ils se corroborent mutuellement dès
le premier tour, au lieu d'attendre un rebond.

### Ce que ça implique techniquement

| Élément | Nature du travail | État |
|---|---|---|
| Table `points_depart` | Nouvelle table (type, valeur), plusieurs par investigation | ✅ fait |
| Abstraction `Chercheur` | Généralisation de ce qui est aujourd'hui codé en dur autour de Maigret : un chercheur par type d'entrée, découvert automatiquement comme les modules | ✅ fait |
| `MaigretRunner` devient `ChercheurPseudo` | Un cas particulier parmi d'autres, sans changement de comportement | ✅ fait |
| Corrélation | Les points de départ multiples deviennent autant de références pour le scoring — amélioration directe de la précision | ✅ fait |
| Interface | Formulaire à entrées multiples, avec détection automatique du type saisi | ✅ fait |
| Gating | `recherche_multi_criteres` réservé aux plans payants | ✅ fait |

**Bonne nouvelle** : l'architecture actuelle s'y prête. Le pivot produit déjà des
entités typées (pseudo, e-mail, lien) et sait quoi en faire. Les points de départ
multiples reviennent à **injecter ces entités au départ plutôt qu'en cours de route**.
C'est une généralisation, pas une réécriture.

**Effort estimé** : moyen. Le gros du travail est l'abstraction `Chercheur` ; le reste
suit mécaniquement.

---

## Axe 3 — Recherche par e-mail, téléphone, adresse

C'est ici que se trouve le plus gros gain de valeur, et le plus de pièges.

### E-mail — la situation a changé depuis notre dernier échange

Vous aviez raison de vous méfier de la technique « holehe » : elle ne renvoie qu'un
booléen (« cette adresse est inscrite sur ce site »), aucun lien ni information
exploitable. En creusant la question, j'ai trouvé mieux que de réimplémenter du code
GPL pour un résultat aussi pauvre.

**`user-scanner`** ([kaifcodec/user-scanner](https://github.com/kaifcodec/user-scanner))
est le successeur déclaré de holehe : même principe (tester les formulaires de mot de
passe oublié), mais **licence MIT** — utilisable directement, sans réimplémentation ni
risque juridique — et une couverture bien plus large : **~140 sites pour l'e-mail,
~220 pour le pseudonyme**. Publié récemment, activement maintenu.

Sa limite reste la même que celle que vous avez identifiée : côté e-mail, il ne donne
qu'une présence/absence, jamais un lien ou une donnée de profil. Côté pseudonyme en
revanche, il renvoie de vraies URLs de profils exploitables — un vrai complément à
Maigret sur ce point.

| Technique | Légalité | Fiabilité | Licence |
|---|---|---|---|
| **Gravatar** — le hash MD5 de l'adresse donne accès à un profil public (nom, sites déclarés) | Totale | Bonne quand il existe | API publique |
| **Partie locale comme pseudonyme** — `jean.martin@…` → recherche sur `jean.martin` | Totale | Bonne | *(déjà implémenté)* |
| **Have I Been Pwned** — dans quelles fuites l'adresse apparaît | Totale, service payant officiel | Excellente | ~4 $/mois — **écarté**, outil payant |
| **Vérification MX/SMTP** — l'adresse existe-t-elle ? | Légale | Moyenne (beaucoup de serveurs répondent toujours oui) | — |
| **`user-scanner`** — présence/absence sur ~140 sites (e-mail) et ~220 (pseudo, avec liens) | Zone grise, comme tout test de formulaire de récupération | Bonne, gratuit, sans jeton ni quota | **MIT** — intégrable sans réserve |

La zone grise juridique demeure (interroger un formulaire de récupération de mot de
passe pour une fin autre que récupérer son propre compte n'est pas l'usage prévu),
mais l'obstacle de licence a disparu. Reste la décision de principe : on l'active ou
non, et on le documente dans les CGU si oui.

### Téléphone

Aucun outil gratuit trouvé ne fait mieux, sur ce point précis, que la technique du
formulaire de récupération — et `user-scanner` couvre aussi cet usage pour les
services qui acceptent un numéro en identifiant. `PhoneInfoga`, l'outil de référence du
domaine, est en **GPL-3.0 et non maintenu** (le dépôt précise qu'il peut être archivé
à tout moment) : à ne pas intégrer, mais son principe (recherche du numéro par moteur
de recherche, identification VoIP/opérateur) reste réimplémentable si besoin plus tard.

| Technique | Apport |
|---|---|
| **libphonenumber** (Google, licence Apache 2.0, compatible commercial) | Validité, pays, opérateur, type de ligne (mobile/fixe/VoIP). Immédiat et sans risque. |
| **`user-scanner`** (même outil que ci-dessus) | Présence/absence sur les services acceptant un numéro comme identifiant |
| Recherche du numéro comme chaîne sur les sites couverts | Certaines personnes publient leur numéro |

### Adresse postale

| Technique | Apport |
|---|---|
| **Nominatim** (OpenStreetMap) ou **adresse.data.gouv.fr** | Normalisation, coordonnées, validation. Gratuit et libre. |
| Rapprochement avec les localisations déclarées sur les profils | Devient une **règle de corrélation** supplémentaire, ce qui améliore le scoring existant |

### Conséquence sur le moteur

Chacun de ces éléments devient une entité du graphe, avec ses propres pictogrammes, et
alimente le pivot au même titre qu'un pseudonyme. Le mécanisme existe déjà — il n'y a
qu'à brancher les nouveaux chercheurs dessus.

---

## Axe 4 — Recherche web ouverte et dark web

**Fait le 31/07/2026.** Deux sources complémentaires à Maigret, branchées dans
`executer_recherche` pour le même pseudonyme, gratuites et sans clé. Voir
`app/moteur/sources/` (patron identique aux modules et chercheurs : un fichier = une
source, auto-découverte).

### Recherche web (DuckDuckGo)

Interroge `lite.duckduckgo.com` (version texte, sans JavaScript) en HTTPS classique,
via le client HTTP commun — donc soumise au même limiteur de débit global que tous les
autres modules. Aucune bibliothèque tierce type `ddgs` : elle ferait ses propres
requêtes hors du limiteur, ce qui casserait la garantie « jamais plus vite que le débit
toléré par un site tiers ».

### Recherche dark web (Ahmia)

Interroge `ahmia.fi`, qui indexe les services cachés (.onion) du réseau Tor et exclut
explicitement les contenus illégaux de son index. **Aucune connexion Tor depuis le
serveur** : seule la page de résultats déjà publique, en HTTPS classique, est lue —
titre, extrait et adresse .onion, jamais le contenu du service caché lui-même.

Deux points relevés en le mettant en œuvre, tranchés avec vous le 31/07/2026 :

- Ahmia protège sa page de résultats par un jeton anti-robot à usage unique (un champ
  caché, nom aléatoire à chaque chargement de la page d'accueil, à renvoyer avec la
  recherche). Ce n'est pas une authentification, mais c'est un mécanisme anti-scraping
  — décision : on le reproduit quand même, le risque étant jugé faible (aucune donnée
  protégée, aucun contournement de CAPTCHA).
- Le service est instable côté serveur (erreurs 504 constatées en le testant) : chaque
  échec est traité comme une simple indisponibilité de la source, jamais comme une
  erreur bloquante pour l'investigation.

### Coupler d'autres moteurs dark web : recherche faite, résultat limité

Recherche menée sur l'outil GitHub [`megadose/OnionSearch`](https://github.com/megadose/OnionSearch)
(GPL-3.0 — regardé uniquement pour la liste des moteurs qu'il cible, jamais importé
comme dépendance), qui agrège 16 moteurs de recherche dark web. Résultat : **15 des 16
ne sont accessibles que par leur adresse .onion**, c'est-à-dire qu'il faudrait faire
passer nos requêtes par le réseau Tor lui-même (proxy SOCKS, service Tor à faire
tourner et maintenir) — une décision d'infrastructure à part entière, plus lourde que
l'ajout d'une source, à ne prendre qu'à dessein.

Le seul autre moteur annoncé en clearnet, `darksearch.io`, s'est révélé injoignable
(délai de résolution DNS dépassé) au moment de la vérification : probablement disparu.
Ahmia reste donc la seule source dark web active. Le système (`app/moteur/sources/`)
est construit pour qu'ajouter une source future — un nouveau moteur clearnet qui
apparaîtrait, ou un jour la connectivité Tor — ne demande qu'un nouveau fichier, sans
toucher au reste.

---

## Ce qui est accessible, et ce qui coûte cher

En autohébergement, tout est ouvert : le découpage en paliers ne s'applique qu'aux
instances exploitées comme un service (`MODE_AUTOHEBERGE=false`), et les valeurs
correspondantes vivent dans
[`app/facturation/plans.py`](../backend/app/facturation/plans.py).

Restent trois curseurs qui pèsent réellement sur le coût d'une recherche, et qu'il
faut avoir en tête quelle que soit l'installation :

1. le **volume** de recherches — chacune ouvre des centaines de connexions sortantes ;
2. la **profondeur de rebond** — chaque niveau multiplie les requêtes ;
3. le **nombre de sites analysés** par recherche — principal levier sur la durée,
   environ 0,25 s par site.

Les plafonds correspondants sont dans
[`backend/config.yaml`](../backend/config.yaml) : ils protègent les sites interrogés et
la machine, pas l'usage.

Les **sites sensibles** (pornographie) sont accessibles, mais un compte de ce type
reste en confiance faible sans corroboration indépendante du pseudonyme : c'est la
donnée la plus lourde de conséquences qu'une investigation puisse produire. Détail dans
`app/moteur/sites_sensibles.py`.

Les fuites de données (HIBP) et le connecteur X/Twitter sont écartés : outils payants,
exclus par principe.

---

## Ordre de mise en œuvre recommandé

1. ✅ **Vague A des modules** — dix modules ajoutés le 29/07/2026 : Lobsters,
   Wikipédia, Liberapay, Goodreads, Letterboxd (sans clé), Last.fm et Twitch (clé
   gratuite), Pixelfed, PeerTube, Lemmy (fédivers). S'ajoutent aux six déjà faits
   (Codeberg, Gitee, Bluesky, Dev.to, MixCloud, Steam). SourceHut, Telegram et Ko-fi
   ont été écartés faute d'API publique exploitable pour ce cas d'usage — détail
   dans [docs/ajouter-un-module.md](ajouter-un-module.md).
2. ✅ **`user-scanner` (MIT)** — présence e-mail/pseudo sur ~360 sites, intégré comme
   sous-processus (même patron que Maigret)
3. ✅ **Abstraction `Chercheur`** — prérequis technique de tout le reste
4. ✅ **Points de départ multiples** — backend, API et interface
5. ✅ **Chercheur e-mail** (Gravatar + partie locale + `user-scanner`) — HIBP écarté,
   outil payant
6. ✅ **Chercheur téléphone** (libphonenumber + `user-scanner`)
7. ✅ **Chercheur adresse** (Nominatim + adresse.data.gouv.fr)
8. **Discord** — connecteur officiel gratuit (jeton de bot), seule étape non encore
   commencée de cette feuille de route, selon la demande client réelle. X/Twitter
   écarté (voir ci-dessus).

---

## Décisions ouvertes

1. **`user-scanner`** (test d'existence via les formulaires de récupération, licence
   MIT) : à activer ou non. La question n'est plus juridique (licence propre) mais de
   principe — c'est une zone grise d'usage, à signaler dans le cadre d'utilisation si
   elle est retenue.
2. **GHunt** (investigation Gmail/Google, AGPL-3.0) : gain de valeur potentiellement
   très élevé, mais nécessiterait soit d'accepter les obligations AGPL (publier le
   code de Ops), soit un chantier de réimplémentation à part entière. À isoler
   comme décision distincte, pas pour cette feuille de route.
Tranché : X/Twitter (~200 $/mois) et Have I Been Pwned (~4 $/mois) sont écartés. Le
projet n'intègre aucun service tiers payant, quel que soit le rapport valeur/prix :
c'est ce qui garantit qu'une installation reste gratuite à faire tourner.
