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
| Fonctionnalités testées | 24 |
| Fonctionnent correctement | 18 |
| Défauts trouvés | **6** (dont 3 sérieux) |
| Défauts corrigés et **revérifiés en réel** | **6 / 6** |
| Tests automatisés | 188 → **203** au vert |

Mesures avant / après correction, sur la même cible et le même périmètre :

| | Avant | Après |
|---|---|---|
| Faux comptes injectés par la recherche web | 11 sur 36 | **0** |
| Compte GitHub en double | oui | **non** |
| Recherche par adresse électronique | 733 s, 0 donnée | **140 s, 121 données** |
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

## 5. Ce qui n'a pas pu être testé

- **Rebond (pivot)** en conditions réelles : les recherches de contrôle ont été
  lancées à profondeur 0 pour rester mesurables. Le mécanisme reste couvert par les
  tests automatisés (`test_cycle_investigation.py`).
- **Paiement Stripe réel** : aucun compte Stripe n'existe encore (décision connue).
- **Recherches par téléphone et adresse postale** : lancées, mais le banc de test est
  tombé sur une réponse inattendue avant de recueillir la mesure. Elles restent
  couvertes par les tests automatisés.

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
