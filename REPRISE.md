# Où reprendre

Point d'étape au **02/08/2026**.

## État : application vérifiée de bout en bout

### Téléphone et adresse : l'information trouvée est enfin exploitée (02/08/2026)

Constat parti d'une question simple — « pourquoi la recherche par téléphone ne me rend
que l'opérateur, le pays et des liens ? ». Trois causes distinctes, dont une seule était
un vrai défaut.

**Ce qui est normal et le restera.** `libphonenumber` ne lit que des plages
d'attribution. Un **fixe ne renvoie aucun opérateur** (d'où l'impression qu'il ne reste
que le pays), et sur mobile l'opérateur est celui du bloc d'origine — faux dès qu'il y a
eu portabilité. Aucune source publique ne relie un numéro à une personne privée : les
outils qui le font utilisent des carnets d'adresses aspirés, des bases de fuites ou
l'énumération des messageries, tous exclus par le parti pris du projet.

**Le vrai défaut.** L'outil trouvait la réponse et la jetait. Relevé en base après une
recherche sur `+33140205050` : le nom du Louvre figurait dans **six titres sur huit** et
l'adresse postale complète dans un extrait — le tout enregistré en `lien_externe` et
rien d'autre. L'analyste devait ouvrir huit onglets pour lire ce que l'outil avait déjà
collecté.

Nouveau module `moteur/chercheurs/mentions.py`, partagé entre les chercheurs téléphone
et adresse :

- **nom d'entité par consensus** — retenu seulement s'il concorde sur au moins deux
  domaines distincts. Un titre isolé peut dire n'importe quoi ; c'est le même principe
  que la corrélation des comptes. Sur un numéro de particulier, rien ne fait consensus
  et rien n'est nommé, ce qui est le comportement voulu ;
- **adresse postale** reconnue à sa forme française, en excluant les chiffres du numéro
  recherché pour ne pas prendre un fragment de téléphone pour un numéro de voie ;
- **filtrage à deux critères** — la liste de domaines (élargie : `quinumero.info` et
  consorts passaient au travers) *plus* un critère de contenu (« à qui appartient ce
  numéro ? », « nombre d'opinions »), parce qu'une liste de domaines sera toujours en
  retard sur le web.

Le chercheur par **adresse** n'appliquait aucun filtre : il rendait des itinéraires
RATP, Bing Maps et des estimations MeilleursAgents. Il utilise désormais le même
module.

Vérifié en conditions réelles : `+33140205050` produit `entreprise = « Musée Du Louvre »`
et `localisation = « 34 quai francois mitterrand 75001 Paris »` ; `55 rue du Faubourg
Saint-Honoré` produit `entreprise = « Palais de l'Élysée »`, sans les quatre domaines de
cartographie qui polluaient le résultat. 240 tests au vert.

### Campagne d'évaluation et refonte de la corrélation (02/08/2026)

Sept investigations réelles (les cinq types de recherche, le multi-critères, le rebond,
les paliers gratuit et Pro), puis **vérification manuelle** des URL remontées — code
HTTP *et* contenu de page, ce que les tests automatisés ne font pas.

Le constat central contredit l'intuition de départ : **Maigret fonctionne**. Sur 45 URL
« torvalds » ouvertes à la main, 73 % renvoient un vrai profil consultable, 18 % sont
bloquées par un pare-feu anti-robot, et seules 9 % sont de faux positifs francs
(`discord.com`, `bit.ly`, `bitbucket.org`, `donationalerts.com` — pages génériques sans
identifiant). Le problème n'était pas la découverte, mais **l'homonymie** :
`instagram.com/torvalds` = « Marco Migozzi », `untappd.com/torvalds` = « Torvald
Storaas », Steam = « WTF Gaming », Indonésie. Les modules avaient extrait ces noms ; le
moteur les ignorait et laissait ces comptes à 65 %, « confiance moyenne ».

Sept correctifs, tous vérifiés en conditions réelles :

1. **Départ depuis un compte connu — bogue bloquant.** `investigation.pseudo_initial`
   contenait l'URL brute, d'où un pseudonyme de référence « httpsgithubcomsoxoj » : tous
   les comptes étaient pénalisés pour dissimilarité et le compte GitHub *fourni par
   l'analyste* obtenait **0 %**. Nouvelle fonction `pseudos_reference()` dans
   `services/investigation.py`, appliquée aux trois points d'appel (corrélation,
   détecteur de pivot ×2). GitHub remonte à 88 %.
2. **`coherence_temporelle` ne lève plus le plafond de score.** Sa tolérance de trois
   ans se déclenchait sur presque tout compte daté et suffisait, avec le seul
   pseudonyme, à franchir le seuil « 2 signaux = 85 ». Nouvel attribut
   `RegleCorrelation.compte_pour_plafond`.
3. **Nouvelle règle `identite_contradictoire`** — la seule qui sache dire *non*. Un nom
   d'au moins deux mots, étranger au pseudonyme comme aux autres comptes, vaut −0.7.
   Trois précautions tirées de cas réels : deux comptes au même nom étranger ne se
   corroborent pas (Instagram + Pinterest = « Marco Migozzi ») ; un nom recopié du
   pseudonyme par le site ne compte pas (« Torvalds Torvalds » sur SoundCloud) ; un nom
   d'un seul mot n'est pas une identité civile (« NaraKa »).
4. **Sites sensibles plafonnés en confiance faible** sans corroboration indépendante.
   OnlyFans, Xvideos et ChaturBate passent de 65 % à 39 %.
5. **Comptes non corroborés repliés** dans l'interface, derrière « *N* comptes au
   pseudonyme identique, non vérifiés ». Nouveau champ API `nb_signaux_corroborants`,
   calculé en une requête agrégée avec la même définition que le plafonnement.
6. **Palier gratuit refondu** : 10 recherches sur 100 sites (au lieu de 15 sur 200),
   mais avec enrichissement et **un** niveau de rebond supervisé. Il rendait 84 comptes
   dont zéro en confiance élevée — il démontrait le contraire de ce qu'il vend.
7. **« Accès API » retiré** de la grille tarifaire : rien ne l'implémente.

Effet global mesuré sur « torvalds » (500 sites) : de **123 comptes indifférenciés à 5**
affichés par défaut. Palier gratuit : de 84 comptes / 0 en confiance élevée à 52 / 5,
avec 3 rebonds proposés.

**Un piège rencontré, à retenir** : le worker Celery ne recharge pas le code (pas de
`--reload`). Toute modification du moteur de corrélation exige de le **redémarrer**,
sinon les scores recalculés restent ceux de l'ancienne version — ce qui donne
l'impression que le correctif ne marche pas.

235 tests au vert. Les limites connues et **non résolues** (agrégation par moyenne
pondérée qui fausse l'ordre, homonymes de la même famille, faux positifs structurels de
Maigret) sont listées dans le README, section « Limites connues ».

### Export PDF, double authentification, migration Stripe (31/07/2026)

Trois chantiers menés en parallèle suite à la décision de payer via **Stripe plutôt
que Gumroad**.

**Export PDF** (`app/services/export_pdf.py`, via `reportlab`, déjà présent en
dépendance transitive de Maigret) — rapport présentable (tableau des profils, détail
des données extraites par site, avertissement légal), réservé aux plans possédant
`export_pdf`. Testé hors serveur avec des données contenant `<script>` et `&` : le
texte est bien échappé, aucune injection de balise dans le PDF produit.

**Double authentification (TOTP)** — activation en deux temps (générer un secret et
des codes de secours via `/auth/2fa/activer`, confirmer avec un vrai code via
`/auth/2fa/confirmer` : sans cette confirmation, une erreur de scan aurait verrouillé
le compte). Le secret est chiffré en base avec Fernet (clé dérivée de `CLE_SECRETE`,
voir `app/securite/totp.py`) — une fuite de la base seule ne suffit pas à cloner le
second facteur. La connexion en deux appels : le premier renvoie 401/`totp_requis` si
le compte a activé la 2FA, le second fournit le code. Page « Mon compte » ajoutée à la
navigation pour gérer l'activation/désactivation.

**Migration Gumroad → Stripe** — remplacement complet (aucune vente réelle n'avait
encore eu lieu, la conversion de données existantes n'était donc pas nécessaire).
Différences de fond avec Gumroad :
- Stripe **pilote l'abonnement depuis l'application** (sessions Checkout et portail de
  facturation créées par nos soins), alors que Gumroad ne faisait que notifier ;
- le lien organisation ↔ client Stripe passe par une **métadonnée** posée à la
  création de la session de paiement (`organisation_id`, `plan_code`), pas par une
  recherche par email côté webhook — plus robuste ;
- le webhook est **signé** (`Stripe-Signature` + secret d'endpoint), alors que Gumroad
  ne proposait qu'un secret partagé en paramètre d'URL ;
- `activer_abonnement`/`resilier_abonnements` ont déménagé de `services/gumroad.py`
  vers `facturation/abonnements.py`, provider-neutre : le code métier (quotas,
  garde-fous par plan) ne dépend plus du fournisseur de paiement.

**Vérifié dans le navigateur le 31/07/2026**, avec le compte de test existant (plan
Pro) : activation de la 2FA (secret et codes de secours affichés, QR code généré),
confirmation avec un vrai code TOTP calculé côté navigateur, déconnexion puis
reconnexion en deux temps (mot de passe → 401/`totp_requis` → mot de passe + code →
200), désactivation avec mot de passe et code, export PDF téléchargé avec succès sur
une investigation réelle (200, contenu `%PDF`). Bouton « Souscrire » de la page
Abonnement cliqué sans clé Stripe configurée : erreur claire affichée (« Stripe n'est
pas configuré sur ce serveur »), pas de plantage, reste de l'application inchangée.

Deux migrations Alembic manquaient sur la base PostgreSQL locale après ce chantier
(colonnes TOTP, puis renommage Gumroad → Stripe) : la connexion échouait en 500 tant
qu'elles n'étaient pas appliquées. **Après un `git pull` incluant ce chantier**,
`alembic upgrade head` puis `python -m app.scripts.initialiser_plans` sont
indispensables avant de relancer l'API (déjà rappelé plus haut, mais particulièrement
important cette fois : la connexion casse silencieusement en 500 sinon).

**Non testé** : un vrai paiement Stripe Checkout de bout en bout, ni un vrai webhook
signé — aucun compte Stripe n'existe encore (décision de l'utilisateur, à créer plus
tard). La logique de traitement des webhooks (activation, résiliation, déduplication)
est vérifiée par les tests automatisés, en contournant la vérification de signature.
Avant la première vente : créer le compte Stripe, les prix, l'endpoint de webhook
(voir « Facturation via Stripe » dans le [README](README.md)), puis faire un paiement
de test avec `stripe listen --forward-to localhost:8010/api/v1/stripe/webhook`.

172 tests automatisés au vert (154 avant ce chantier + 18 nouveaux : export PDF,
TOTP, traitement des webhooks Stripe).

### Protection contre la création de comptes en série (31/07/2026)

Le palier gratuit offrant 15 recherches par mois, rien n'empêchait jusqu'ici un
script d'en obtenir un volume illimité en créant des comptes à la chaîne. Quatre
protections, **sans service tiers ni frais** — même parti pris que « APIs publiques
uniquement » : faire passer chaque visiteur par un service de détection de robots
révélerait à un tiers qui s'intéresse à l'outil.

1. **Épreuve de calcul à l'inscription** (`app/securite/anti_bot.py`) — le serveur
   pose une énigme que seul l'essai exhaustif résout. Format Altcha, mais écrit
   entièrement ici, serveur et client, sans dépendance. Signature HMAC (on ne peut
   pas fabriquer son propre défi), horodatage dans le sel (péremption), et marquage
   du défi consommé dans Redis (pas de rejeu).
2. **Plafond de 3 organisations par IP et par 24 h** — compteur à fenêtre fixe.
   Incrémenté même quand l'inscription échoue ensuite, sinon un script sonderait les
   adresses déjà prises sans jamais consommer son plafond. Les invitations ne sont
   pas concernées : rejoindre une organisation n'ouvre aucun quota.
3. **Limitation de débit par IP** (`app/infra/limiteur_entrant.py`) sur
   l'inscription, la connexion et la création d'investigation. Le verrou par compte
   (8 échecs) ne couvrait pas le balayage de nombreuses adresses depuis une même
   origine, chaque compte restant sous son seuil.
4. **Refus des adresses jetables** à l'inscription. La liste existait déjà dans le
   chercheur `email`, où elle sert au contraire à *signaler* — deux usages opposés,
   d'où un module partagé (`app/securite/domaines_jetables.py`).

Trois points d'attention :

- **`derriere_un_proxy_de_confiance` est à `false`** dans `config.yaml` et doit le
  rester tant qu'aucun proxy n'est déployé. À `true` sans proxy, `X-Forwarded-For`
  vient du client : il suffirait de le changer à chaque requête pour se présenter
  sous une nouvelle adresse. À passer à `true` **le jour du déploiement derrière
  Caddy/Nginx**, faute de quoi tous les utilisateurs partageront un seul compteur.
- **Redis n'est pas indispensable** : chaque compteur retombe en mémoire du processus
  s'il manque. La règle reste appliquée, seule sa portée est réduite. Dégrader la
  portée, pas la règle — même parti pris que `infra/limiteur.py`.
- **L'inscription en ligne de commande ne fonctionne plus** sans désactiver
  `anti_abus.actif` : c'est voulu, mais cela surprend. Noté dans le README.

**Vérifié dans le navigateur le 31/07/2026** : épreuve demandée au chargement de la
page, résolue en **240 ms pour 39 000 essais** (~300 ms au pire cas, sur une machine
courante) pendant la saisie — l'utilisateur ne voit rien et n'attend pas ; inscription
acceptée (201). Côté serveur : appel sans preuve refusé (400), et 14 tentatives de
connexion d'affilée donnent 10 × 401 puis 4 × 429, exactement le réglage annoncé.

13 tests dédiés, 154 au total.

### Nouvelle grille tarifaire (30/07/2026)

Grille **arrêtée**, appliquée par le code et verrouillée par un test
(`test_quotas_et_rebonds_des_quatre_paliers` : une modification involontaire d'un
quota est un incident commercial, pas un détail technique).

| | Gratuit | Starter | Pro | Entreprise |
|---|---|---|---|---|
| Recherches / mois | 15 | 100 | 500 | 2500 |
| Rebonds | ❌ | 2 | 5 | 10 |
| Sites par recherche | 200 | 1000 | tous | tous |
| Types de recherche | pseudo + mail | tous | tous | tous |
| Sites sensibles | ❌ | ✅ | ✅ | ✅ |

Trois points d'attention rencontrés :

- **Un plafond serveur dur à 4 rebonds** (`pivot.profondeur_plafond_serveur`)
  aurait écrasé en silence les 5 et 10 rebonds vendus. Relevé à 10 ; c'est
  `max_recherches_par_investigation` qui contient réellement le coût, pas la
  profondeur.
- **Le nombre de sites** est un nouveau champ de plan (`max_sites_analyses`,
  0 = sans limite), donc une colonne et une migration Alembic. Le sélecteur du
  formulaire grise les paliers hors plan au lieu de laisser la requête échouer.
- **Les sites sensibles** ne peuvent pas être identifiés par les seules étiquettes
  de Maigret : une quinzaine de sites manifestement adultes n'en portent aucune
  (Fansly, Eporner, AdultFriendFinder…). Un filtrage par mots-clés a été écarté —
  il produit des faux positifs (« illustrators.ru » contient « lust »,
  « antiscam.space » contient « cam »). D'où deux sources : les étiquettes, plus
  une liste explicite de domaines. Détail dans
  `backend/app/moteur/sites_sensibles.py`.

Le filtrage est appliqué à l'**enregistrement** des comptes, point de passage unique
de toute découverte quelle que soit sa source (Maigret, user-scanner, chercheur
spécialisé) : le placer dans chaque runner obligerait à y penser à chaque nouveau
chercheur.

Après un `git pull` sur une autre machine, appliquer :

```bash
cd backend && .venv/Scripts/python -m alembic upgrade head && .venv/Scripts/python -m app.scripts.initialiser_plans
```

### Icônes du graphe : taille, centrage et stabilité au zoom (30/07/2026)

Le problème signalé depuis deux sessions est résolu, et **vérifié par la mesure**
cette fois. Trois défauts distincts, aucun visible à la lecture du code :

1. `background-position-x/y` de Cytoscape ne place pas le centre de l'image : le
   pourcentage interpole l'espace *libre* autour d'elle. Avec une icône occupant
   82 % du nœud, demander « 42 % » ne la décalait que de 1,4 % — la correction de
   centrage de la session précédente était donc quasiment sans effet.
2. L'icône faisait 82 % du cadre pour **toutes** les formes, alors qu'un chevron
   n'offre que 33 % de place et un losange 50 %. L'icône débordait de la forme.
3. Un SVG déclaré avec `viewBox` seul n'a pas de taille intrinsèque : le navigateur
   lui attribue 150 × 150 (mesuré), d'où un rendu variable selon le zoom.

Toute la géométrie est désormais portée par le SVG, qui déclare ses dimensions.
Cytoscape reçoit une consigne unique pour tous les types : « dessine cette image sur
100 % du nœud, centrée ». L'échelle et le décalage viennent du plus grand carré
inscriptible dans chaque forme, calculé numériquement à partir des polygones réels de
Cytoscape. La taille des nœuds compense la place offerte par leur forme, de sorte que
tous les pictogrammes s'affichent à la même taille (26 à 36 px, contre 14 à 39 px).

**Vérification** : le panneau navigateur n'étant pas affiché côté utilisateur,
`requestAnimationFrame` ne se déclenche pas et Cytoscape ne peint jamais — aucune
capture d'écran n'est possible. Contourné avec `cy.png()`, qui force un rendu
synchrone, puis mesure des pixels : côté de l'icône identique aux zooms 1 et 3
(nœud rendu de 78 à 234 px), conforme à la cible à 0,005 près, décalages stables, et
**100 % de l'encre à l'intérieur de la forme**.

### Élément de départ principal de type quelconque (30/07/2026)

Jusqu'ici, seul l'élément *principal* d'une investigation devait être un
pseudonyme ; les éléments complémentaires pouvaient déjà être d'un autre type.
Ce n'est plus le cas : l'élément principal peut désormais lui aussi être une
adresse électronique, un numéro de téléphone, un compte connu ou une adresse
postale, avec le même contrôle de type et de droits par plan que les éléments
complémentaires.

Quand l'élément principal n'est pas un pseudonyme, la recherche large
(Maigret) part du premier pseudonyme découvert par les chercheurs spécialisés
(ex. partie locale d'une adresse électronique, pseudo extrait d'une URL de
compte) ; si aucun n'est découvert, Maigret est simplement sauté et
l'investigation se termine avec les seuls résultats des chercheurs
spécialisés.

Backend, API, schéma, tâche Celery et interface (formulaire d'accueil) mis à
jour ; 6 nouveaux tests. **Vérifié dans le navigateur le 30/07/2026** : le
formulaire affiche bien le sélecteur de type, la détection automatique
fonctionne (un lien collé passe en « Adresse d'un compte connu ») et le texte
d'aide s'adapte au type choisi.

### Départ depuis le lien d'un compte : extraction du pseudonyme corrigée (30/07/2026)

Partir du lien d'un compte fonctionnait déjà en théorie, mais échouait
silencieusement sur la plupart des liens réels, parce que le pseudonyme était
cherché dans le **dernier** segment de l'URL, et que tout nom contenant un
point était refusé. Concrètement :

| Lien collé | Avant | Après |
|---|---|---|
| `instagram.com/jean.martin/` | *rien* (point refusé) | `jean.martin` |
| `instagram.com/jeanmartin/reels/` | `reels` | `jeanmartin` |
| `x.com/jeanmartin/status/1234` | `1234` | `jeanmartin` |
| `tiktok.com/@jean.martin` | *rien* | `jean.martin` |
| `instagram.com/p/ABC123/` | `ABC123` | *rien* (c'est une publication) |

Le pseudonyme est désormais cherché au **début** du chemin, là où il se trouve
réellement ; les points sont acceptés (courants sur Instagram, TikTok,
Facebook) ; les préfixes de profil sont suivis (`linkedin.com/in/…`,
`reddit.com/user/…`) ; et les adresses qui ne désignent pas un profil
(publication, sous-forum, nom de fichier, identifiant numérique) sont écartées
au lieu de gaspiller une recherche. La validité du pseudonyme s'appuie
maintenant sur `pseudo_exploitable`, qui fait déjà autorité ailleurs dans le
projet — les deux se contredisaient.

Effet de bord bienvenu : la partie locale des adresses électroniques avec un
point (`jean.martin@…`) devient elle aussi un pivot exploitable.

**Vérifié en conditions réelles le 30/07/2026** : investigation lancée depuis
`https://www.instagram.com/mark.zuckerberg/` → compte Instagram enregistré à
100 % (fourni par l'analyste, donc tenu pour certain), pseudonyme
`mark.zuckerberg` extrait, recherche large Maigret déclenchée, **54 comptes
trouvés** et 57 éléments dans le graphe. Avant le correctif, ce même lien
donnait 1 seul nœud et aucune recherche.

### Démarrage en un clic (30/07/2026)

`demarrer.bat` et `arreter.bat` à la racine du projet automatisent le
lancement complet et son arrêt. Détail dans la section « Relancer le projet »
ci-dessous.

**Lenteur de démarrage corrigée.** L'interface paraissait très lente à
charger. Vite n'y était pour rien (il démarre en 250 ms, mesuré) : le script
lançait le worker Celery *juste avant* l'interface, et le chargement de la base
Maigret (3221 sites) sature processeur et disque pendant environ deux minutes —
l'interface démarrait donc sur une machine étranglée. Pire, le navigateur
s'ouvrait après un délai fixe de 8 secondes, sans vérifier que quoi que ce soit
soit prêt.

Le script attend maintenant une disponibilité **réelle** à chaque étape
(PostgreSQL via `pg_isready`, API via `/api/sante`, interface via une requête
HTTP), prépare le code de l'interface avant d'ouvrir le navigateur, et ne lance
le worker qu'**en dernier**. L'interface est donc utilisable immédiatement ; seule
la première recherche attend le worker, ce que le script annonce explicitement.

Le parcours complet a été exécuté en conditions réelles (Maigret sur de vrais
pseudonymes, PostgreSQL, Redis, worker Celery, interface dans le navigateur). Tout
fonctionne : inscription, recherche, corrélation, enrichissement, rebond automatique,
graphe, explication des scores, exports, quotas et gating par plan.

134 tests automatisés au vert.

### Points de départ multiples — disponibles dans l'interface

Une investigation peut désormais partir de plusieurs éléments à la fois : pseudonyme,
adresse électronique, numéro de téléphone, adresse d'un compte connu, adresse postale.
Le type est deviné à la frappe et reste modifiable ; les types non inclus dans le plan
sont signalés avant l'envoi plutôt que refusés après.

Vérifié en conditions réelles le 29/07/2026 : investigation lancée sur le pseudonyme
`soxoj` + l'adresse `soxoj@protonmail.com` → 17 comptes par le pseudonyme, 12 par
l'adresse, 29 comptes après déduplication.

### Suite de la vague A des modules (29/07/2026)

Dix modules d'enrichissement supplémentaires : Lobsters, Wikipédia, Liberapay,
Goodreads, Letterboxd (aucune clé requise), Last.fm et Twitch (clé gratuite à
configurer dans `.env`, sinon le module reste simplement inactif), Pixelfed,
PeerTube, Lemmy (fédivers, même principe que Mastodon). Vingt-deux modules au total.
SourceHut, Telegram et Ko-fi ont été examinés et écartés faute d'API publique
adaptée — détail dans [docs/ajouter-un-module.md](docs/ajouter-un-module.md).

### Autres corrections du jour

- Le bandeau d'avertissement légal en haut de chaque page a été retiré.
- Le message d'erreur d'enrichissement (« Aucun module ne couvre le site ») restait
  affiché en changeant de nœud sélectionné dans le graphe, tant qu'aucune nouvelle
  erreur ne survenait. Corrigé en forçant le remontage du panneau de détail à chaque
  changement de sélection.
- Icônes des nœuds du graphe agrandies et recentrées. Deux formes (« tag » pour les
  pseudonymes alternatifs, « vee » pour les liens) ne centraient pas leur pictogramme
  sur leur centre visuel réel — corrigé par calcul géométrique exact à partir des
  définitions de forme de Cytoscape. **Toujours pas vérifié visuellement** au
  30/07/2026, après une seconde tentative : le panneau de navigateur intégré n'est
  pas affiché côté utilisateur, ce qui empêche toute capture d'écran (le graphe se
  rend bien, cela a été confirmé côté code). À confirmer d'un simple coup d'œil à la
  prochaine ouverture d'une investigation comportant plusieurs types de nœuds.

## Relancer le projet

**Double-cliquez sur `demarrer.bat`** à la racine du projet : il fait tout d'un coup
(Docker, API, interface, puis worker), attend que chaque brique réponde vraiment, et
ouvre le navigateur. Pour tout arrêter, `arreter.bat`.

Détail de ce que fait `demarrer.bat`, pour dépannage ou lancement manuel :

```bash
docker compose up -d postgres redis
```

Puis trois terminaux :

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

```bash
cd backend && .venv/Scripts/python -m celery -A app.taches.celery_app worker -Q recherche,enrichissement,pivot,maintenance --pool=solo --loglevel=info
```

```bash
cd frontend && npm run dev
```

Interface sur http://localhost:5183

> Sous Windows, `--pool=solo` est indispensable pour Celery.
>
> Si Docker Desktop refuse de démarrer avec une erreur de socket
> (`dockerInference` ou `engine.sock` inaccessibles), voir la section « Incident
> Docker » plus bas.

## Compte de test existant

`remi@cabinet-test.fr` / `PhraseDePasseLongue2026` — organisation « Cabinet de test »,
plan Pro, rebond automatique sur 2 niveaux.

Pour passer une autre organisation en plan payant sans passer par Stripe :

```bash
cd backend && .venv/Scripts/python -c "from app.db.session import portee_session; from app.modeles import Organisation, Plan; from app.facturation.abonnements import activer_abonnement; from sqlalchemy import select; s=portee_session().__enter__(); org=s.scalar(select(Organisation).where(Organisation.slug=='VOTRE-SLUG')); plan=s.scalar(select(Plan).where(Plan.code=='pro')); activer_abonnement(s, org, plan, stripe_customer_id='cus_test', stripe_subscription_id='sub_test'); s.commit(); print('ok')"
```

## Ce qui reste à faire

1. **Envoi des courriels d'invitation** — le lien d'invitation s'affiche à l'écran ;
   il faut le transmettre manuellement pour l'instant. Nécessite un service d'envoi
   (Brevo, Scaleway TEM, ou SMTP classique).
2. **Export PDF du rapport** — JSON et CSV fonctionnent.
3. **2FA** — les champs `totp_secret` et `totp_actif` existent déjà en base.
4. **Volet juridique** — base légale (intérêt légitime), AIPD, contrat de
   sous-traitance client. À faire valider par un juriste **avant la première vente**.
   Voir [docs/rgpd.md](docs/rgpd.md).
5. **Jeton GitHub** — renseigner `GITHUB_TOKEN` dans `.env` fait passer la limite de
   60 à 5000 requêtes par heure. Indispensable dès plusieurs clients.

## Points de performance observés

- Une recherche Maigret sur 50 sites prend environ 25 secondes.
- Le **premier** lancement après démarrage du worker ajoute environ 2 minutes :
  l'import de la bibliothèque Maigret et le chargement de sa base de 3221 sites sont
  lourds. Les recherches suivantes n'en souffrent pas. En production, les workers
  tournant en continu, cela ne se produit qu'au déploiement.
- L'enrichissement d'un profil prend 1 à 3 secondes (appels réseau).

## Incident Docker rencontré le 29/07/2026

Docker Desktop refusait de démarrer avec :

```
initializing Inference manager: listening on unix://...\dockerInference:
remove ...: The file cannot be accessed by the system.
```

Sockets Unix orphelins que Windows ne parvient pas à supprimer. Résolu ainsi :

1. arrêt de tous les processus Docker ;
2. renommage des dossiers `%LOCALAPPDATA%\Docker\run` et
   `%LOCALAPPDATA%\docker-secrets-engine` (Docker les recrée au démarrage) ;
3. passage de `EnableDockerAI` à `false` dans
   `%APPDATA%\Docker\settings-store.json` (sauvegarde conservée sous
   `settings-store.json.sauvegarde_searcher`).

Si l'incident se reproduit, appliquer la même procédure.

## Rappel des décisions arrêtées

- Paiement par **Stripe** (Checkout + portail client), pas Gumroad (abandonné le
  31/07/2026, avant toute vente réelle)
- Graphe stocké dans **PostgreSQL**, pas de Neo4j
- Modules uniquement sur **APIs publiques** (GitHub, Reddit, Mastodon, GitLab,
  Hacker News, Keybase)
- Maigret lancé avec `--no-recursion` en permanence, sans quoi il pivote de lui-même
  et le palier gratuit obtiendrait gratuitement une fonctionnalité payante
