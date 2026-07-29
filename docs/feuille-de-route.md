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
| **Licence GPL-3.0** | Intégrer ce code dans Searcher contaminerait juridiquement le produit. En SaaS pur (le code n'est jamais distribué), la GPL-3.0 ne force pas la publication — c'est l'AGPL qui couvre ce cas. Mais la position est fragile, et interdit toute installation chez un client. |
| **Compte Instagram réel obligatoire** | L'outil se connecte avec de vrais identifiants. Chaque client devrait fournir les siens, ou vous exposeriez les vôtres. |
| **Violation des conditions d'Instagram** | Le scraping authentifié est explicitement interdit. Bannissement du compte à la clé, et exposition juridique pour vous en tant qu'éditeur. |
| **Fiabilité** | L'outil casse à chaque changement de Meta, ce qui arrive plusieurs fois par an. |

**Ce qui reste possible sur Instagram** : l'API Graph officielle, qui exige un compte
Business et une validation par Meta, et ne donne accès qu'à des comptes professionnels
ayant consenti. Utile pour de la veille de marque, pas pour une investigation.

### Les autres grandes plateformes

| Plateforme | Voie légale | Coût | Verdict |
|---|---|---|---|
| **X / Twitter** | API officielle v2 | ~200 $/mois (palier Basic) | **Réaliste** pour un plan Entreprise. Fiable et sans risque juridique. |
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

| Site | Intérêt |
|---|---|
| Lobsters, Codeberg *(fait)*, SourceHut | communautés techniques, profils riches |
| Last.fm | API publique avec clé gratuite, historique d'écoute et localisation |
| Wikipédia / Wikimedia | contributions publiques, très révélatrices d'intérêts et de fuseau horaire |
| Telegram (canaux publics) | via l'API Bot, sur canaux publics uniquement |
| Twitch | API officielle, clé gratuite |
| Pixelfed, PeerTube, Lemmy | fédivers : mêmes API que Mastodon, quasi gratuit à ajouter |
| Ko-fi, Liberapay | financement participatif, souvent liés à une identité réelle |
| Goodreads, Letterboxd | via flux RSS publics quand l'API manque |

### Vague B — Clé API gratuite (effort faible, configuration client)

Steam *(fait via XML)*, Twitch, Last.fm, Discord (jeton de bot), YouTube (quota
gratuit). Chacune demande une clé à configurer dans `.env` : à documenter clairement,
puisque vous n'êtes pas développeur.

### Vague C — X / Twitter via l'API officielle (effort moyen, coût réel)

~200 $/mois. À réserver aux plans Pro et Entreprise, avec répercussion du coût dans
le prix. C'est la seule voie propre vers X.

### Ce que je recommande d'écarter

Instagram, Facebook, LinkedIn, TikTok par scraping. Le rapport risque/bénéfice est
mauvais : bannissements, casse permanente, exposition juridique de l'éditeur.

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
de Searcher. La seule voie propre serait de réimplémenter son approche (API Google
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

| Élément | Nature du travail |
|---|---|
| Table `points_depart` | Nouvelle table (type, valeur), plusieurs par investigation |
| Abstraction `Chercheur` | Généralisation de ce qui est aujourd'hui codé en dur autour de Maigret : un chercheur par type d'entrée, découvert automatiquement comme les modules |
| `MaigretRunner` devient `ChercheurPseudo` | Un cas particulier parmi d'autres, sans changement de comportement |
| Corrélation | Les points de départ multiples deviennent autant de références pour le scoring — amélioration directe de la précision |
| Interface | Formulaire à entrées multiples, avec détection automatique du type saisi |
| Gating | `recherche_multi_criteres` réservé aux plans payants |

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
| **Have I Been Pwned** — dans quelles fuites l'adresse apparaît | Totale, service payant officiel | Excellente | ~4 $/mois |
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

## Répartition proposée par palier

Mise à jour suite à votre consigne : recherche par e-mail/téléphone/adresse et outils
spécialisés (modules, `user-scanner`) disponibles dès le palier Starter, au même titre
que les modules d'enrichissement existants.

| Fonctionnalité | Gratuit | Starter | Pro | Entreprise |
|---|---|---|---|---|
| Recherche par pseudonyme | ✅ | ✅ | ✅ | ✅ |
| Modules d'enrichissement (tous, y compris les nouveaux) | ❌ | ✅ | ✅ | ✅ |
| **Démarrer depuis un compte** | ❌ | ✅ | ✅ | ✅ |
| **Recherche par e-mail** | ❌ | ✅ | ✅ | ✅ |
| **Recherche par téléphone** | ❌ | ✅ | ✅ | ✅ |
| **Recherche par adresse** | ❌ | ✅ | ✅ | ✅ |
| **Points de départ multiples** | ❌ | 2 maximum | 5 | illimité |
| Fuites de données (HIBP) | ❌ | ❌ | ✅ | ✅ |
| Connecteur X / Twitter | ❌ | ❌ | ❌ | ✅ |

Ce qui reste échelonné par palier, et pourquoi : la **profondeur de rebond** et le
**nombre de points de départ simultanés** restent les vrais leviers de coût
d'infrastructure (chaque point de départ ou niveau de rebond multiplie les requêtes
sortantes) — c'est sur ces deux curseurs que la progression Starter → Pro → Entreprise
continue de se justifier, plutôt que sur l'accès aux types de recherche eux-mêmes.

À ajuster ensemble : cette répartition reste une proposition.

---

## Ordre de mise en œuvre recommandé

1. **Vague A des modules** — gain immédiat, aucun risque, chaque module est autonome
2. **`user-scanner` (MIT)** — présence e-mail/pseudo sur ~360 sites, intégrable tel
   quel comme sous-processus (même patron que Maigret)
3. **Abstraction `Chercheur`** — prérequis technique de tout le reste
4. **Points de départ multiples** — la fonctionnalité payante que vous demandez
5. **Chercheur e-mail** (Gravatar + partie locale + HIBP + `user-scanner`)
6. **Chercheur téléphone** (libphonenumber + `user-scanner`)
7. **Chercheur adresse** (Nominatim)
8. **Discord et X** — connecteurs officiels, selon la demande client réelle

Les étapes 1 et 2 sont indépendantes entre elles et de l'étape 3.

---

## Décisions qui vous reviennent

1. **`user-scanner`** (test d'existence via les formulaires de récupération, licence
   MIT) : on l'active ou non ? La question n'est plus juridique (licence propre) mais
   de principe — c'est une zone grise d'usage, à documenter dans les CGU si retenu.
2. **GHunt** (investigation Gmail/Google, AGPL-3.0) : gain de valeur potentiellement
   très élevé, mais nécessiterait soit d'accepter les obligations AGPL (publier le
   code de Searcher), soit un chantier de réimplémentation à part entière. À isoler
   comme décision distincte, pas pour cette feuille de route.
3. **Abonnement X / Twitter à ~200 $/mois** : on l'intègre pour le palier Entreprise ?
4. **Have I Been Pwned à ~4 $/mois** : à intégrer ? Le rapport valeur/prix est excellent.
5. **Répartition par palier** mise à jour ci-dessus : à valider ou corriger.
