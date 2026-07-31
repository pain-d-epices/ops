# Architecture

## Vue d'ensemble

```
┌────────────┐   HTTPS / WSS   ┌──────────────┐
│  Frontend  │────────────────▶│   FastAPI    │  authentification, quotas, API, WebSocket
│  (à faire) │◀────────────────│              │
└────────────┘                 └──────┬───────┘
                                      │ mise en file
                               ┌──────▼───────┐
                               │    Redis     │  file de tâches, pub/sub temps réel,
                               └──────┬───────┘  limitation de débit globale
                    ┌─────────────────┼─────────────────┐
             ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
             │   worker    │   │   worker    │   │ planificateur│
             │  recherche  │   │ enrichisst. │   │   (beat)     │
             └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
                    └─────────────────┼─────────────────┘
                               ┌──────▼───────┐
                               │  PostgreSQL  │  métier + graphe (nœuds/arêtes)
                               └──────────────┘
```

## Décisions structurantes

### Le graphe est dans PostgreSQL, pas dans Neo4j

Un graphe d'investigation compte quelques milliers de nœuds au maximum : deux tables
(`noeuds_graphe`, `aretes_graphe`) suffisent largement. Ajouter une base graphe
signifierait une seconde base à installer, sauvegarder, surveiller et sécuriser, pour
un gain nul à cette échelle.

Tout l'accès passe par `app/moteur/graphe/depot.py` : une migration ultérieure vers
Neo4j se limiterait à réécrire ce fichier, sans toucher au code métier.

### SQLAlchemy synchrone partout

Les tâches Celery sont synchrones par nature. Utiliser le mode asynchrone uniquement
côté API imposerait de maintenir **deux** couches d'accès aux données en parallèle.
FastAPI exécute les endpoints déclarés en `def` dans un pool de threads, ce qui rend ce
choix parfaitement viable — et nettement plus simple à opérer.

### Maigret est bridé volontairement

Maigret dispose d'une recherche récursive intégrée : à partir de « torvalds », il lance
spontanément une recherche sur « Victor Torvalds ». **C'est du pivot.**

Le laisser faire aurait deux conséquences inacceptables :
- le palier gratuit bénéficierait gratuitement de la fonctionnalité payante ;
- la profondeur de recherche deviendrait incontrôlable, donc le coût aussi.

L'option `--no-recursion` est donc **toujours** passée, et `--no-extracting` l'est pour
les plans sans la fonctionnalité « modules ». Le pivot est intégralement piloté par
notre orchestrateur, qui applique les règles commerciales.

### Deux files de tâches

Une recherche Maigret dure 2 à 10 minutes et monopolise un worker ; un enrichissement
prend quelques secondes. Les séparer évite qu'une file de recherches longues bloque
l'enrichissement et le pivot.

---

## Structure du code

```
backend/app/
├── config.py              # .env (secrets) + config.yaml (métier), séparés
├── main.py                # application FastAPI, gestion des exceptions métier
│
├── db/                    # base déclarative, sessions
├── modeles/               # SQLAlchemy — toutes les tables portent organisation_id
│
├── securite/
│   ├── mots_de_passe.py   # Argon2id
│   ├── jetons.py          # JWT d'accès
│   └── dependances.py     # ⚠ contexte_courant : point de contrôle de l'isolation
│
├── facturation/
│   ├── plans.py           # définition des paliers (amorçage uniquement)
│   ├── abonnements.py     # résolution du plan actif
│   ├── quotas.py          # compteurs atomiques
│   └── garde.py           # exiger_fonctionnalite, bornage de la profondeur
│
├── moteur/
│   ├── maigret_runner.py  # sous-processus, parsing ndjson, progression
│   ├── correlation/
│   │   ├── base.py        # structures pures — testables sans base de données
│   │   ├── regles/        # une règle = un fichier, auto-découvert
│   │   ├── registre.py    # chargement + poids depuis config.yaml
│   │   └── scoreur.py     # agrégation + plafonnement par nombre de signaux
│   ├── pivot/
│   │   ├── detecteur.py   # quelles données sont pivotables
│   │   └── orchestrateur.py # quatre garde-fous cumulatifs
│   └── graphe/depot.py    # seule couche connaissant les tables du graphe
│
├── modules/               # un fichier = un site, auto-découvert
├── infra/
│   ├── limiteur.py        # seau à jetons Redis, GLOBAL par domaine
│   ├── http.py            # client commun : débit, délais, tentatives
│   └── evenements.py      # bus Redis pub/sub vers le WebSocket
│
├── services/              # logique métier appelée par les tâches
├── taches/                # Celery
└── api/v1/                # endpoints
```

---

## Flux complet d'une investigation

```
POST /investigations
  ├─ vérifie le rôle, les CGU acceptées
  ├─ vérifie la limite d'investigations simultanées
  ├─ consomme le quota « recherches » (atomiquement)
  ├─ BORNE les options : profondeur et mode selon le plan
  ├─ journalise (auteur, cible, horodatage)
  └─ met en file  lancer_investigation
                        │
                        ▼
      executer_recherche(pseudo, profondeur=0)
        ├─ Maigret --no-recursion [--no-extracting si plan gratuit]
        ├─ progression → Redis → WebSocket → navigateur
        ├─ crée les profils + nœuds du graphe
        └─ rescore l'ensemble des profils
                        │
              plan avec « modules » ?
              ┌─────────┴─────────┐
             non                 oui
              │                   ▼
              │       enrichir_investigation
              │         ├─ un module par site, profils au score suffisant
              │         ├─ consomme le quota « enrichissements »
              │         ├─ crée données extraites + nœuds + arêtes
              │         └─ rescore (les nouvelles données changent tout)
              │                   │
              │           pivot disponible ?
              │           ┌───────┴───────┐
              │          non             oui
              │           │               ▼
              │           │     detecter_et_pivoter
              │           │       ├─ détecte les données pivotables
              │           │       ├─ arbitre : plan, profondeur, budget, anti-cycle
              │           │       ├─ mode supervisé  → propositions en attente
              │           │       └─ mode automatique → nouvelle recherche ↺
              └───────────┴───────────────┘
                          ▼
                 finaliser_investigation
```

### Pourquoi rescorer globalement à chaque étape

Les règles croisées — avatar identique, adresse partagée, lien réciproque — font
dépendre le score d'un profil **de tous les autres**. Rescorer un profil isolément
produirait des scores incohérents entre eux. Toute arrivée de données déclenche donc un
recalcul complet de l'investigation.

C'est aussi pourquoi marquer un profil comme faux positif modifie le score des autres :
un profil rejeté cesse de servir de point de comparaison.

---

## Les quatre garde-fous du pivot

Appliqués dans cet ordre par `OrchestrateurPivot.arbitrer()` :

1. **Fonctionnalité** — le plan doit inclure `pivot` ;
2. **Profondeur** — `min(demandé, plan.profondeur_pivot_max, plafond_serveur)` ;
3. **Budget** — 25 recherches maximum par investigation (`config.yaml`) ;
4. **Anti-cycle** — toute valeur déjà proposée ou explorée est mémorisée.

Sans le quatrième, une investigation tournerait en boucle : « john » trouve un email
dont la partie locale est « john », qui relance une recherche sur « john »…

---

## Points de sécurité à ne jamais contourner

| Mécanisme | Où | Pourquoi |
|---|---|---|
| Filtre `organisation_id` sur chaque requête | tous les endpoints | Une omission expose les investigations d'un client à un autre |
| `404` et non `403` sur ressource d'autrui | `investigations.py`, `ws.py` | Un `403` confirmerait l'existence de la ressource |
| Revérification du plan dans les tâches Celery | `taches/*` | Un abonnement peut expirer entre la mise en file et l'exécution |
| Bornage serveur des options client | `garde.py` | Le frontend n'est jamais une source de vérité |
| Plafond dur de profondeur | `config.yaml` | Aucun plan, même modifié en base, ne peut le dépasser |
| Limitation de débit globale par site | `limiteur.py` | Sinon la montée en charge commerciale fait bannir l'IP du service |

---

## Schéma de données

**Multi-tenant** : `organisations`, `utilisateurs`, `appartenances` (rôle par
rattachement), `invitations`

**Facturation** : `plans`, `abonnements` (client et souscription Stripe),
`compteurs_usage` (un par organisation et par mois), `evenements_stripe` (webhooks
bruts, rejouables)

**Investigation** : `investigations`, `executions_recherche` (une par appel Maigret,
pivots compris, avec la sortie brute conservée), `profils_identite`,
`donnees_extraites`, `signaux_correlation` (explication du score),
`propositions_pivot`

**Graphe** : `noeuds_graphe` (dédupliqués par `cle_unicite`), `aretes_graphe`

**Traçabilité** : `journal_acces` (écriture seule)

La sortie brute de Maigret est conservée dans `executions_recherche.resultat_brut` :
cela permet de **rejouer la corrélation après ajustement des poids** sans relancer
aucune requête réseau — utile pour calibrer le scoring sur des cas réels.

---

## Ajouter une règle de corrélation

Même principe que les modules : créez un fichier dans
`app/moteur/correlation/regles/`, héritez de `RegleCorrelation`, implémentez
`evaluer()`. Déclarez le poids dans `config.yaml`.

```python
class RegleMaNouvelleRegle(RegleCorrelation):
    nom = "ma_regle"          # doit correspondre à la clé dans config.yaml
    libelle = "Mon critère"

    def evaluer(self, profil, contexte) -> ResultatRegle | None:
        if pas_de_donnee_exploitable:
            return None       # s'abstenir, et NON renvoyer 0
        return ResultatRegle(
            score=0.8,        # -1 (pénalité) à 1
            explication="Formulé pour être lu par un analyste",
        )
```

**Règle d'or** : renvoyez `None` quand vous ne pouvez pas vous prononcer. Un `0`
pénaliserait le profil pour une donnée simplement absente, et ferait plafonner tous
les comptes non enrichis à un score artificiellement bas.
