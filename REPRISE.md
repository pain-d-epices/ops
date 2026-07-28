# Où reprendre

Point d'étape au **28/07/2026**, à lire en premier à la reprise.

## État

| Partie | État |
|---|---|
| Backend | ✅ Complet, 69 tests au vert, migration validée sur PostgreSQL 16 |
| Frontend | ⚠️ Écrit et compilé sans erreur, **jamais exécuté avec le backend** |

## À faire en premier : la vérification de bout en bout

C'est l'étape qui a été interrompue. Rien ne prouve encore que l'interface fonctionne
réellement avec l'API — seulement qu'elle compile.

### 1. Démarrer l'infrastructure

```bash
docker compose up -d postgres redis
```

### 2. Préparer la base (une seule fois)

```bash
cd backend && .venv/Scripts/python -m alembic upgrade head
```

```bash
cd backend && .venv/Scripts/python -m app.scripts.initialiser_plans
```

### 3. Lancer les trois processus, chacun dans son terminal

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

```bash
cd backend && .venv/Scripts/python -m celery -A app.taches.celery_app worker -Q recherche,enrichissement,pivot,maintenance --pool=solo --loglevel=info
```

```bash
cd frontend && npm run dev
```

> Sous Windows, `--pool=solo` est indispensable pour Celery.

### 4. Parcours à vérifier dans le navigateur (http://localhost:5173)

1. Créer un compte (acceptation des CGU obligatoire) ;
2. lancer une recherche sur un pseudonyme réel — par exemple `torvalds`, en réglant
   « sites à scanner » assez bas dans les options avancées pour que ce soit rapide ;
3. vérifier que la barre de progression avance **en temps réel** (WebSocket) ;
4. vérifier que le graphe se remplit au fur et à mesure, sans que les nœuds déjà
   placés ne sautent ;
5. cliquer sur un compte : le panneau latéral doit détailler le calcul de son score ;
6. tester la vue tableau, un verdict manuel, puis l'export JSON.

### 5. Pour tester l'enrichissement et le rebond

Ces fonctionnalités sont réservées aux plans payants. Pour passer une organisation au
plan Pro sans passer par Gumroad :

```bash
cd backend && .venv/Scripts/python -c "from app.db.session import portee_session; from app.modeles import Organisation, Plan; from app.services.gumroad import activer_abonnement; from sqlalchemy import select; s=portee_session().__enter__(); org=s.scalar(select(Organisation)); plan=s.scalar(select(Plan).where(Plan.code=='pro')); activer_abonnement(s, org, plan, cle_licence='TEST'); s.commit(); print('Plan pro active pour', org.nom)"
```

Un jeton GitHub dans `.env` (`GITHUB_TOKEN`) est fortement recommandé : sans lui,
l'API GitHub limite à 60 requêtes par heure.

## Points restants après cette vérification

- Envoi des courriels d'invitation (le lien s'affiche à l'écran pour l'instant)
- Export PDF du rapport (JSON et CSV fonctionnent)
- 2FA (champs déjà prévus en base)
- **Volet juridique avant commercialisation** : base légale, AIPD, contrat de
  sous-traitance client — voir [docs/rgpd.md](docs/rgpd.md)

## Rappel des décisions déjà arrêtées

- Paiement par **Gumroad** (clé de licence), pas Stripe
- Graphe stocké dans **PostgreSQL**, pas de Neo4j
- Modules uniquement sur **APIs publiques** (GitHub, Reddit, Mastodon, GitLab,
  Hacker News, Keybase)
- Maigret est lancé avec `--no-recursion` en permanence, sans quoi il pivote de
  lui-même et le palier gratuit obtiendrait gratuitement une fonctionnalité payante
