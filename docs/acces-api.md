# Accès API : état réel et ce qu'il resterait à faire

## En résumé : la fonctionnalité n'existe pas

Le code de fonctionnalité `api` (`API_PUBLIQUE` dans
[`app/facturation/plans.py`](../backend/app/facturation/plans.py)) est **déclaré et
accordé, mais vérifié nulle part**. Il n'y a :

- aucun modèle de clé d'API en base ;
- aucune authentification autre que le cookie de session du navigateur ;
- aucun endpoint qui appelle `exiger_fonctionnalite(plan, API_PUBLIQUE)`.

Concrètement, aucune organisation ne peut piloter l'outil autrement que depuis un
navigateur authentifié par cookie. Ce n'est pas un bogue : la fonctionnalité n'a jamais
été construite.

## D'où elle sort

Du **premier commit backend** (`8be7f72`, 27/07/2026, « Socle backend »), où le projet
était conçu comme un service en ligne : le code de fonctionnalité a été posé par
analogie avec les grilles tarifaires habituelles, sans avoir été spécifié, et il y est
resté par inertie.

**Conséquence à retenir** : ne pas annoncer cet accès comme disponible avant de l'avoir
construit. Il n'apparaît donc ni dans la documentation d'installation, ni dans
l'interface.

## Ce qu'il faudrait construire

### 1. Modèle de clé d'API

Une table `cles_api` : identifiant, `organisation_id`, libellé donné par son porteur,
empreinte de la clé (jamais la clé en clair — même traitement qu'un mot de passe),
préfixe visible pour l'identifier dans une liste, date de création, dernière
utilisation, date de révocation. La clé complète n'est montrée **qu'une fois**, à la
création.

### 2. Authentification par clé

Une dépendance FastAPI qui accepte un en-tête `Authorization: Bearer <clé>` en
alternative au cookie, résout l'organisation, et refuse si le plan ne possède pas
`API_PUBLIQUE`. Le reste du contrôle d'accès (quotas, gating par plan, isolation entre
organisations) s'applique alors sans modification, puisqu'il dépend du plan et de
l'organisation, pas du mode d'authentification.

### 3. Quotas et débit propres à l'API

Les quotas mensuels existants s'appliquent déjà par organisation. Il faut y ajouter
une **limite de débit par clé** (requêtes par minute) : sans elle, une clé
Entreprise permet de saturer les workers à elle seule.

### 4. Périmètre volontairement réduit

Ouvrir tout `/api/v1` reviendrait à exposer l'administration de l'organisation et la
facturation. Un accès API devrait se limiter à : créer une investigation, lire son
état, lire ses résultats, exporter. Rien qui touche aux utilisateurs, aux invitations
ou à l'abonnement.

### 5. Journalisation distincte

Les appels par clé doivent être identifiables dans le journal d'audit
(`ActionJournal`), ne serait-ce que pour pouvoir répondre à « qu'est-ce qui a été
consulté avec cette clé ? » — question qui arrivera tôt ou tard, RGPD ou litige.

## Lien avec la protection anti-automatisation

Ces deux sujets sont le même sujet vu des deux côtés : l'API est de l'automatisation
**autorisée et facturée**, le reste est de l'automatisation **à empêcher**. Il est
cohérent de construire d'abord la seconde (voir
[protection-anti-automatisation.md](protection-anti-automatisation.md)), puis
d'ouvrir la première comme une exception contractuelle.
