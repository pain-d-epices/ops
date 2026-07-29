# Où reprendre

Point d'étape au **29/07/2026**.

## État : application vérifiée de bout en bout

Le parcours complet a été exécuté en conditions réelles (Maigret sur de vrais
pseudonymes, PostgreSQL, Redis, worker Celery, interface dans le navigateur). Tout
fonctionne : inscription, recherche, corrélation, enrichissement, rebond automatique,
graphe, explication des scores, exports, quotas et gating par plan.

124 tests automatisés au vert.

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
  définitions de forme de Cytoscape. **Non vérifié visuellement cette session** : le
  panneau de navigateur intégré n'était pas affiché côté utilisateur, empêchant toute
  capture d'écran. À confirmer visuellement à la prochaine ouverture d'une
  investigation avec plusieurs types de nœuds.

## Relancer le projet

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

Interface sur http://localhost:5173

> Sous Windows, `--pool=solo` est indispensable pour Celery.
>
> Si Docker Desktop refuse de démarrer avec une erreur de socket
> (`dockerInference` ou `engine.sock` inaccessibles), voir la section « Incident
> Docker » plus bas.

## Compte de test existant

`remi@cabinet-test.fr` / `PhraseDePasseLongue2026` — organisation « Cabinet de test »,
plan Pro, rebond automatique sur 2 niveaux.

Pour passer une autre organisation en plan payant sans passer par Gumroad :

```bash
cd backend && .venv/Scripts/python -c "from app.db.session import portee_session; from app.modeles import Organisation, Plan; from app.services.gumroad import activer_abonnement; from sqlalchemy import select; s=portee_session().__enter__(); org=s.scalar(select(Organisation).where(Organisation.slug=='VOTRE-SLUG')); plan=s.scalar(select(Plan).where(Plan.code=='pro')); activer_abonnement(s, org, plan, cle_licence='TEST'); s.commit(); print('ok')"
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

- Paiement par **Gumroad** (clé de licence), pas Stripe
- Graphe stocké dans **PostgreSQL**, pas de Neo4j
- Modules uniquement sur **APIs publiques** (GitHub, Reddit, Mastodon, GitLab,
  Hacker News, Keybase)
- Maigret lancé avec `--no-recursion` en permanence, sans quoi il pivote de lui-même
  et le palier gratuit obtiendrait gratuitement une fonctionnalité payante
