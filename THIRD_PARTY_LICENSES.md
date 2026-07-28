# Dépendances tierces et licences

Recensement des bibliothèques utilisées par Searcher, avec leur licence et son
implication pour une commercialisation en logiciel propriétaire.

**Aucune dépendance sous licence copaleft (GPL/AGPL/LGPL) n'est utilisée.** Toutes les
licences listées ci-dessous (MIT, BSD, Apache 2.0, HPND) autorisent l'usage dans un
produit commercial fermé, sans obligation de publier le code source de Searcher.

> À mettre à jour à chaque ajout de dépendance. Vérifiez systématiquement la licence
> **avant** d'intégrer une bibliothèque : une dépendance GPL contraindrait la
> distribution de l'ensemble du produit.

---

## Composant central

| Bibliothèque | Licence | Rôle | Implication |
|---|---|---|---|
| [Maigret](https://github.com/soxoj/maigret) | MIT | Recherche de pseudonymes sur ~3000 sites | Usage commercial libre, y compris dans un produit payant fermé. Seule obligation : conserver la mention de copyright et le texte de licence (voir ci-dessous). |

### Mention de licence Maigret à conserver

```
MIT License — Copyright (c) 2020 Soxoj

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

Cette mention doit apparaître dans les crédits de l'application (page « À propos »).

---

## Backend

| Bibliothèque | Licence | Rôle |
|---|---|---|
| FastAPI | MIT | Cadriciel web (API REST et WebSocket) |
| Uvicorn | BSD-3-Clause | Serveur ASGI |
| Starlette | BSD-3-Clause | Socle ASGI de FastAPI |
| Pydantic / pydantic-settings | MIT | Validation des données et configuration |
| SQLAlchemy | MIT | ORM et accès base de données |
| Alembic | MIT | Migrations de schéma |
| psycopg (v3) | LGPL-3.0 **avec exception** | Pilote PostgreSQL |
| Celery | BSD-3-Clause | File de tâches asynchrones |
| redis-py | MIT | Client Redis |
| httpx | BSD-3-Clause | Client HTTP des modules de site |
| tenacity | Apache-2.0 | Politique de nouvelles tentatives |
| argon2-cffi | MIT | Hachage des mots de passe |
| PyJWT | MIT | Jetons d'authentification |
| PyYAML | MIT | Lecture de `config.yaml` |
| RapidFuzz | MIT | Distance entre chaînes (corrélation de pseudonymes) |
| ImageHash | BSD-2-Clause | Hash perceptuel des avatars |
| Pillow | MIT-CMU (HPND) | Traitement d'images |
| email-validator | The Unlicense | Validation des adresses électroniques |
| websockets | BSD-3-Clause | Transport WebSocket |

### Point d'attention : psycopg

`psycopg` (version 3) est distribué sous **LGPL-3.0 avec une exception explicite**
autorisant la liaison depuis un logiciel propriétaire, y compris dans une distribution
binaire. C'est le pilote PostgreSQL de référence en Python et son usage commercial est
courant et sans ambiguïté.

Cette exception couvre notre usage (installation comme dépendance, sans modification de
la bibliothèque). En cas de modification du code source de psycopg lui-même, les
obligations LGPL s'appliqueraient à la version modifiée : ne modifiez pas cette
bibliothèque.

---

## Frontend

| Bibliothèque | Licence | Rôle |
|---|---|---|
| React / React DOM | MIT | Bibliothèque d'interface |
| React Router | MIT | Routage entre les pages |
| TanStack Query (React Query) | MIT | Cache et synchronisation des données |
| Cytoscape.js | MIT | Rendu du graphe interactif |
| cytoscape-fcose | MIT | Algorithme de disposition du graphe |
| Vite | MIT | Outil de construction |
| TypeScript | Apache-2.0 | Typage statique |

Aucune de ces dépendances n'est copaleft : le code du frontend peut rester
propriétaire. Aucun framework CSS n'est utilisé (styles écrits à la main), ce qui
évite une dépendance supplémentaire à auditer.

---

## Outils de développement (non distribués)

Ces outils ne sont pas embarqués dans le produit livré ; leur licence n'a donc aucune
incidence sur la distribution.

| Outil | Licence |
|---|---|
| pytest / pytest-cov | MIT |
| Ruff | MIT |

---

## Services externes appelés

Ces services ne sont pas des dépendances logicielles, mais leurs conditions
d'utilisation s'appliquent aux appels effectués.

| Service | Usage | Conditions |
|---|---|---|
| API GitHub | Enrichissement de profils | API publique documentée. 60 requêtes/h sans jeton, 5000/h avec. Usage commercial autorisé. |
| API Reddit | Enrichissement de profils | Point d'accès public `about.json`. User-Agent identifiable requis. |
| API Mastodon | Enrichissement de profils | API publique standard, dépend de la politique de chaque instance. |
| API GitLab | Enrichissement de profils | API v4 publique. |
| API Hacker News | Enrichissement de profils | API Firebase publique, sans limite documentée. |
| API Keybase | Enrichissement de profils | API publique de consultation. |
| API Gumroad | Vérification des licences d'abonnement | Nécessite un jeton vendeur. |

**Choix délibéré** : seuls des sites à API publique et documentée sont couverts par un
module. Les plateformes fermées (X/Twitter, Instagram, Facebook, TikTok) exigent une
authentification et interdisent le scraping dans leurs conditions d'utilisation ;
développer un module pour ces sites exposerait l'éditeur à un risque juridique et à des
ruptures de service permanentes.

---

## Vérification des licences

Pour lister les licences de l'ensemble de l'arbre de dépendances installé :

```bash
pip install pip-licenses && pip-licenses --format=markdown --with-urls
```

Recherchez toute occurrence de `GPL` non suivie de « with exception », `AGPL`, ou
`SSPL` : ces licences seraient incompatibles avec une distribution propriétaire.
