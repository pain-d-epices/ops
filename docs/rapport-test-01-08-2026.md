# Rapport de test complet — 1er août 2026

Test de bout en bout de l'application, **en conditions réelles** : stack complète
(PostgreSQL, Redis, API, worker Celery, interface), réseau ouvert, cible publique
`torvalds` — le même pseudonyme que le parcours de validation du 29/07/2026, ce qui
permet de comparer.

Ce document sert de référence : il fixe les mesures obtenues, ce qui marche, ce qui ne
marchait pas, et ce qui a été corrigé.

---

## Verdict d'ensemble

| | |
|---|---|
| Fonctionnalités testées | 27 |
| Défauts trouvés | **12** (dont 6 graves) |
| Défauts corrigés et **revérifiés en réel** | **12 / 12** |
| Tests automatisés | 188 → **221** au vert |

Mesures avant / après correction, sur les mêmes cibles et le même périmètre :

| | Avant | Après |
|---|---|---|
| Faux comptes injectés par la recherche web | 11 sur 36 | **0** |
| Faux compte injecté par la recherche téléphone | 1 (YouTube inexistant) | **0** |
| Compte GitHub en double | oui | **non** |
| Recherche par adresse électronique | 733 s, 0 donnée | **140 s, 121 données** |
| Recherche par téléphone | métadonnées seules | **identifie le Musée du Louvre** |
| Recherche par adresse postale | l'adresse saisie | **identifie l'agence BNP à cette adresse** |
| Rebond (mode automatique, profondeur 1) | 1 recherche, 0 rebond | **5 recherches, 58 comptes** |
| Nœuds « localisation » pour « Portland, OR » | 9 (un par lettre) | **1** |
| Connexion PostgreSQL retenue pendant l'appel réseau | 733 s | **non retenue** |

Le moteur est **solide sur son cœur de métier** : la corrélation identifie
correctement le vrai compte et l'explique. Les défauts trouvés se concentrent sur les
périphéries récemment ajoutées (recherche web, recherche par adresse électronique) et
sur un point d'architecture qui menaçait la stabilité en charge.

---

## 1. Ce qui fonctionne bien

### Corrélation et scoring — le point fort

Recherche `torvalds` sur 50 sites, **74 secondes** :

| Mesure | Résultat |
|---|---|
| Comptes trouvés | 36 |
| Compte GitHub réel de la cible | **score 89, confiance élevée** ✅ |
| Explication du score | 4 signaux : pseudonyme (3.0), avatar (2.5), cohérence des dates (0.98), bio (0.68) |
| Graphe produit | 43 nœuds, 46 arêtes |

La **vérité terrain est trouvée et bien notée**, avec le détail de son calcul. C'est
ce qui compte le plus : un analyste peut contester la conclusion plutôt que la subir.

Le plafonnement à 65 pour les comptes à signal unique fonctionne : 21 comptes trouvés
sur le seul pseudonyme restent à 65, sans jamais atteindre la confiance élevée.

### Sécurité et facturation — aucune faille trouvée

| Vérification | Résultat |
|---|---|
| Épreuve anti-robot | ✅ résolue en 6 077 essais (~2 s) |
| Rejeu d'une preuve déjà utilisée | ✅ refusé (HTTP 400) |
| Plafond de comptes par adresse IP | ✅ actif (a bloqué mes propres tests en série) |
| Mot de passe erroné | ✅ refusé (401) |
| Double authentification (TOTP) | ✅ activation, confirmation, 8 codes de secours |
| Isolation entre organisations | ✅ **404** et non 403 sur ressource d'autrui |
| Gating par plan (gratuit) | ✅ pseudo + e-mail seulement |
| Gating par plan (pro) | ✅ les 5 types ouverts |
| Refus téléphone en gratuit | ✅ 403 |
| Refus export CSV/PDF en gratuit | ✅ 403 / export JSON autorisé |
| Bornage serveur des options | ✅ profondeur 10 demandée → 5 appliqués (plan pro) |

### Exports

Les trois formats fonctionnent : JSON (20 554 o), CSV (3 619 o), PDF (10 503 o),
générés en moins d'une seconde.

---

## 2. Défauts trouvés et corrigés

### 🔴 Grave — Les données du profil Gravatar étaient purement perdues

**Constat.** Une recherche par adresse électronique trouvait bien un profil Gravatar
(nom affiché, localisation, avatar), mais la base contenait **zéro donnée extraite**.

**Cause.** `donnees_extraites.profil_id` était obligatoire. Or ces informations
décrivent la personne recherchée, pas un compte trouvé. Quand aucun compte n'existait
— précisément le cas où elles avaient le plus de valeur — elles étaient jetées.

**Conséquence.** L'information la plus fiable de la recherche par adresse (une page
que la personne a elle-même remplie) n'était ni affichée, ni utilisée pour la
corrélation, ni exploitable comme rebond.

**Correction.** `profil_id` rendu optionnel (migration `b7d41e05c3a2`). Ces données
sont désormais enregistrées, et **pivotables sans condition de score** — il n'y a pas
de profil douteux à écarter, et c'est souvent la meilleure piste de l'enquête.

**Vérifié en réel** : la même recherche conserve désormais **121 données extraites au
lieu de 0**, dont le nom affiché, la localisation et l'empreinte d'avatar du profil
Gravatar, rattachés au point de départ.

### 🔴 Grave — Une connexion base de données retenue 12 minutes

**Constat.** Une recherche par adresse électronique tenait une connexion PostgreSQL
ouverte pendant **733 secondes**.

**Cause.** L'appel réseau du chercheur se faisait *à l'intérieur* de la transaction —
exactement ce que le projet s'interdit ailleurs, avec un commentaire explicite dans
`executer_module` : « le pool serait saturé et l'API deviendrait indisponible pour
tout le monde ».

**Conséquence.** Quelques recherches par adresse simultanées auraient saturé le pool
de connexions et rendu l'API indisponible **pour tous les clients**.

**Correction.** `traiter_point_depart` découpé en trois, sur le modèle déjà en place
pour l'enrichissement : vérification (transaction courte) → appel réseau (**hors
transaction**) → enregistrement (transaction courte).

### 🔴 Grave — La recherche web injectait de faux comptes

**Constat.** Sur 36 comptes trouvés, **11 n'étaient pas des comptes** : des articles
d'encyclopédie et de presse (Britannica, ZDNet, Wikipédia, Google Scholar,
Baidu Baike, Grokipedia), enregistrés comme profils avec un score « moyen ».

**Cause.** La recherche web retenait tout résultat de DuckDuckGo. Or un moteur
généraliste répond surtout par des pages *au sujet de* la personne.

**Conséquence.** Environ **30 % de faux comptes** dans la liste de résultats, et
autant de bruit dans le graphe — pour un outil dont la valeur est la précision.

**Correction.** Un résultat n'est retenu que si l'adresse désigne un profil **de cette
personne**, via `pseudo_depuis_url` qui fait déjà autorité dans le projet.

**Vérifié en réel après correction** : la même recherche rend **27 profils au lieu de
36**, avec **zéro** page encyclopédique ou de presse — et le compte GitHub réel
toujours à 89, en confiance élevée. Aucune perte de vrai résultat.

### 🟠 Le même compte apparaissait deux fois

**Constat.** Le compte GitHub de la cible figurait deux fois : `www.github.com/torvalds`
(Maigret) et `github.com/torvalds/linux` (recherche web).

**Cause.** La déduplication comparait les **adresses**, alors que deux pages d'un même
site peuvent désigner le même compte.

**Correction.** Déduplication sur le **compte** (`domaine + nom d'utilisateur`) et non
sur l'URL. Les sous-domaines restent distincts : `gist.github.com/torvalds` est bien
un autre service. **Vérifié en réel** : une seule entrée GitHub après correction.

### 🟠 « Portland » éclaté en neuf nœuds, un par lettre

**Constat.** Le graphe d'une recherche par adresse contenait des nœuds
« P », « o », « r », « t », « l », « a », « n », « d ».

**Cause.** `currentLocation` de l'API Gravatar est une **chaîne** (`"Portland, OR"`),
pas une liste. La boucle itérait donc sur ses caractères.

**Correction.** Normalisation des champs Gravatar hétérogènes (chaîne / liste /
dictionnaire) avant traitement. Le même piège existait sur `name` et `urls` : traité
aussi. **Vérifié en réel** : `localisations = ['Portland, OR']`, un seul nœud.

### 🟠 Recherche par adresse : 12 minutes pour rien

**Constat.** 733 secondes, **zéro résultat**. `user-scanner` consommait la totalité de
son délai de 600 s puis rendait une liste vide.

**Cause.** Beaucoup des ~144 sites interrogés ne répondent jamais ; l'attente se
cumule jusqu'au délai maximal.

**Correction.** Délai ramené de 600 s à **180 s** dans `config.yaml`, avec la mesure
qui le justifie en commentaire.

**Vérifié en réel** : la même recherche passe de **733 s à 140 s**, et rapporte cette
fois de vraies données (voir le défaut précédent) — soit **5 fois plus rapide, avec un
résultat au lieu d'aucun**.

### Traçabilité ajoutée au passage

Impossible, avant, de savoir d'où venait un compte (Maigret ? recherche web ?
user-scanner ?). Chaque profil porte désormais sa `source_decouverte`.

**C'est ce qui a permis de trancher un faux diagnostic pendant ce test même** :
`en.wikipedia.org` et `scholar.google.com` semblaient être du bruit de la recherche
web ; la traçabilité a montré qu'ils venaient de Maigret — page utilisateur Wikipédia
légitime d'un côté, entrée « Google Scholar » de la base Maigret de l'autre.

---

## 3. Arrêt d'une recherche en cours (fonctionnalité demandée)

Construit et **validé en conditions réelles** : recherche lancée sur 3 000 sites
(~13 minutes si menée à terme), interrompue en plein vol.

| Mesure | Résultat |
|---|---|
| Réponse de l'API | immédiate (HTTP 200) |
| Arrêt du sous-processus Maigret | **1 à 2 secondes** |
| Statut final | `annulee`, stable (jamais repeint en « terminée ») |
| Seconde annulation | refusée proprement (409) |
| Résultats déjà trouvés | conservés et consultables |

**Pourquoi un arrêt « coopératif » et non un `revoke` Celery** : le worker tourne en
pool `solo` sous Windows — le processus qui exécute la tâche *est* le worker. Le tuer
arrêterait le service pour tous les clients. De plus, une investigation est une chaîne
de tâches : révoquer le maillon courant laisserait partir les suivants.

Un drapeau est donc posé en base (Redis servant de cache de lecture rapide), que
chaque étape consulte à ses points de reprise.

**Quota** : rendu **seulement si la recherche n'a rien trouvé**. Rembourser une
recherche fructueuse permettrait d'enchaîner « je lance, je récupère, j'annule, je
suis remboursé » — soit un volume gratuit illimité.

**Limite assumée** : un scan Maigret interrompu ne rend aucun résultat partiel, car il
n'écrit son rapport qu'à la fin. Ce qui est conservé, ce sont les comptes déjà
enregistrés par les étapes précédentes.

---

## 4. Points de vigilance restants

### La qualité des résultats dépend de la base Maigret, qu'on ne maîtrise pas

`scholar.google.com/scholar?q=torvalds` est remonté comme « compte » : c'est une page
de résultats de recherche, pas un profil. Cela vient de la base de sites de Maigret,
pas de notre code. Le moteur de corrélation le note d'ailleurs faiblement (40).

Piste si le besoin se confirme : étendre la règle `site_douteux` de `config.yaml`,
qui pénalise déjà `instructables.com` et `wikipedia.org`.

### 86 % des résultats en « confiance moyenne »

Sur 36 comptes, 31 étaient classés « moyen » — dont 21 exactement à 65, le plafond des
comptes à signal unique. Le classement discrimine donc peu **tant que
l'enrichissement n'a pas eu lieu**. Ce n'est pas un défaut du plafonnement (qui est
une protection voulue contre les faux positifs), mais cela mérite d'être su : sur un
pseudonyme courant, l'essentiel du tri se joue à l'enrichissement.

### La recherche dark web n'a rien pu être mesuré

Ahmia n'a renvoyé aucun résultat exploitable sur la cible testée, et son instabilité
(erreurs 504 déjà constatées le 31/07) empêche d'en tirer une mesure fiable. La
source échoue proprement, sans bloquer l'investigation — c'est le comportement voulu,
mais son apport réel reste à démontrer sur des cas où le dark web a du sens.

### `top_sites` hors bornes est refusé, pas ramené à la borne

Demander 99 999 sites renvoie une erreur 422 plutôt que d'appliquer le maximum. C'est
défendable (message clair), mais en léger écart avec la doctrine affichée « le serveur
borne les options ». Sans conséquence pratique : l'interface ne propose pas de valeur
hors bornes.

---

## 5. Deuxième passe : téléphone, adresse et rebond

Ces trois fonctionnalités n'avaient pas pu être mesurées lors de la première passe.
Testées ensuite en conditions réelles, elles se sont révélées **inexploitables en
l'état** — trois défauts supplémentaires, corrigés et revérifiés.

### 🔴 Grave — La recherche par téléphone fabriquait de faux comptes

**Constat.** Une recherche sur `+33184944000` produisait un compte
`https://youtube.com/@+33184944000`. Un identifiant YouTube ne peut pas contenir de
« + » : ce compte n'existe pas.

**Cause.** `user-scanner` était appelé en mode **nom d'utilisateur** avec le numéro.
Or un numéro de téléphone n'est pas un nom d'utilisateur.

**Conséquence.** L'outil affirmait à l'analyste que la cible possédait un compte
inexistant. Pour un outil dont la sortie sert à identifier des personnes réelles,
c'est le défaut le plus grave possible.

**Correction.** `user-scanner` retiré de ce chercheur. **Vérifié** : plus aucun
compte produit par une recherche téléphone.

### 🔴 La recherche par téléphone ne cherchait nulle part

**Constat.** Une fois le faux compte retiré, il ne restait que l'opérateur et la
région — des métadonnées déductibles du numéro, qui ne désignent personne.

**Correction.** Recherche du numéro sur le web ouvert, avec deux enseignements tirés
de la mesure :

- **le format compact est le seul qui fonctionne.** Cherché `0140205050`, le numéro
  du Louvre remonte l'annuaire inversé, Infobel et `contact.louvre.fr`. Cherché
  `01 40 20 50 50`, le moteur traite les groupes comme des mots séparés et renvoie
  des calculatrices ;
- **les guillemets font échouer la requête** : `lite.duckduckgo.com` renvoie zéro
  résultat sur une expression entre guillemets.

Les annuaires inversés génériques (Truecaller, Tellows, RoboKiller…) sont écartés :
ils publient une page pour *tout* numéro, y compris inexistant.

**Vérifié en réel** : `+33140205050` est correctement identifié comme le **Musée du
Louvre**, avec le site officiel `contact.louvre.fr` en piste.

### 🟠 La recherche par adresse ne rapportait rien

**Constat.** Elle renvoyait l'adresse normalisée, la ville et les coordonnées — soit
ce que l'analyste venait de saisir.

**Correction.** Recherche de l'adresse normalisée sur le web ouvert.

**Vérifié en réel** sur `10 rue de Rivoli 75004 Paris` : l'outil identifie une
**agence BNP Paribas** et un magasin **Søstrene Grene** à cette adresse, avec les
pages PagesJaunes et Cylex correspondantes.

### 🔴 Grave — Le rebond ne se déclenchait jamais

**Constat.** Une investigation en mode automatique, profondeur 1, plan pro :
**1 seule recherche, 0 proposition de rebond**, alors que 26 comptes avaient été
trouvés et 71 données extraites.

**Cause.** Seul `nom_reel` était déclaré pivotable, or ce champ n'est renseigné que
par Gravatar. `nom_affiche` — renseigné par presque tous les modules, 13 fois dans
cette investigation — n'était jamais exploité. Tous les autres candidats étaient soit
le pseudonyme initial (correctement bloqué par l'anti-cycle), soit sous le seuil de
score.

**Conséquence.** Le rebond, fonctionnalité payante mise en avant à tous les paliers
supérieurs, restait inerte dans le cas le plus courant.

**Correction.** `nom_affiche` devient pivotable, avec les garde-fous existants (deux
mots minimum, graphie compacte plausible, confiance réduite de 40 %).

**Vérifié en réel** : **5 recherches enchaînées au lieu d'1, 58 comptes au lieu de
26**, avec des comptes trouvés au niveau 2. Le rebond découvre `linustorvalds` et
remonte ainsi GitLab, YouTube, Flickr et Tumblr — que la recherche initiale sur
`torvalds` ne voyait pas. Il découvre également `patriciatorvalds`, et avec elle des
comptes Instagram et Facebook : un lien familial que la recherche initiale ne pouvait
pas voir.

### 🟠 Précision du rebond : les homonymes déclenchaient des recherches

**Constat.** Parmi les 5 rebonds proposés, `marcomigozzi` — une personne sans aucun
rapport, nom affiché d'un compte homonyme faussement rattaché.

**Correction.** Un nom ne devient un rebond que s'il partage une racine avec ce qui
est recherché. « Linus Torvalds » et « Patricia Torvalds » restent des pistes
légitimes ; « Marco Migozzi » est écarté.

**Vérifié en réel** : le rebond sans rapport a disparu, les quatre restants portent
tous sur la cible ou son entourage.

### 🟠 Un hash affiché comme adresse électronique

`gravatar_email_md5_hash` était enregistré comme EMAIL : l'analyste voyait
`690495313b377cd5578c2d0f8cb314ee` dans la colonne des adresses. Une empreinte n'est
pas une adresse, et elle n'est pas réversible. Le rapprochement est supprimé.

---

## 6. Ce qui n'a pas pu être testé

- **Paiement Stripe réel** : aucun compte Stripe n'existe encore (décision connue).
- **Recherche dark web** : voir les points de vigilance ci-dessus — Ahmia n'a rien
  renvoyé d'exploitable sur les cibles testées.

---

## 6. Recommandations, par ordre de priorité

1. **Mesurer l'apport réel de la recherche dark web** sur des cas où elle a du sens.
   En l'état, elle coûte deux requêtes par recherche pour un bénéfice non démontré.
2. **Surveiller la durée des recherches par adresse électronique** après le passage à
   180 s. Si elles ne rapportent toujours rien, la question de garder `user-scanner`
   en mode e-mail mérite d'être posée.
3. **Enrichir la liste `site_douteux`** au fil des faux positifs constatés : c'est le
   levier prévu pour ça, et il ne demande aucune modification de code.
4. **Afficher la source de découverte dans l'interface** : la donnée est désormais
   enregistrée, l'exposer aiderait l'analyste à juger.
