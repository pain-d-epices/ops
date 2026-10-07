# Conformité RGPD

Ops traite des **données personnelles de tiers qui n'ont pas consenti à leur
collecte**. C'est le point juridique le plus sensible du produit : il ne se résout pas
par du code seul.

Ce document décrit ce que l'application met en œuvre techniquement, et ce qui reste à
votre charge en tant qu'opérateur de l'instance.

---

## Ce que l'application fait

### 1. Journalisation des accès

Table `journal_acces`, en écriture seule. Chaque recherche est tracée avec :

- l'auteur (utilisateur et organisation), conservé même si le compte est supprimé
- la cible recherchée (le pseudonyme)
- l'horodatage, l'adresse IP et l'agent utilisateur
- l'action (création, enrichissement, pivot, export, verdict, suppression)

C'est la pièce à produire en cas de contrôle, ou de litige sur l'usage abusif du
service par un client. Conservation par défaut : **365 jours**, réglable via
`retention.jours_journaux` dans `config.yaml`.

### 2. Rétention limitée et purge automatique

Chaque investigation reçoit une date de suppression (`supprimer_apres`) à sa création.
Une tâche planifiée quotidienne (3 h 30) supprime celles dont l'échéance est passée.

La suppression est **en cascade et réelle** : profils, données extraites, signaux de
corrélation, nœuds et arêtes du graphe disparaissent. Seule l'entrée de journal
subsiste — la traçabilité des accès relève d'une obligation distincte.

Durée par défaut : **90 jours**, modifiable globalement (`retention.jours_defaut`) ou
par organisation (champ `retention_jours`). Toute modification recalcule les échéances
des investigations existantes.

### 3. Droit à l'effacement

```
DELETE /api/v1/investigations/{id}        # une investigation
DELETE /api/v1/organisation/donnees       # toutes les investigations d'une organisation
```

Suppression immédiate et définitive, sans archivage. C'est ce qu'exige une demande
d'effacement émanant d'une personne figurant dans les résultats.

### 4. Droit à la portabilité

```
GET /api/v1/investigations/{id}/export?format=json
```

L'export JSON reste **accessible à tous les paliers, y compris gratuit** : restreindre
la récupération de ses propres données derrière un paiement serait contraire au RGPD.
Seul l'export CSV, qui relève du confort, est réservé aux plans payants.

### 5. Acceptation explicite du cadre légal

L'acceptation des conditions d'utilisation est obligatoire à l'inscription, et
enregistrée avec sa date et sa version (`cgu_acceptees_le`, `cgu_version_acceptee`).
Toute route déclenchant une recherche est protégée par la dépendance `exiger_cgu` :
sans acceptation, aucune recherche n'est possible.

### 6. Cloisonnement entre clients

Toutes les tables portent `organisation_id`, et chaque requête d'API filtre dessus.
Une investigation demandée par une autre organisation renvoie `404` — jamais `403`, qui
révélerait l'existence de la ressource.

### 7. Minimisation

- Seuls les sites à API publique sont interrogés, et uniquement des profils publics.
- L'enrichissement ne cible que les profils dont le score dépasse un seuil : les
  profils douteux ne font l'objet d'aucune requête supplémentaire.
- La profondeur de pivot est plafonnée côté serveur, ce qui borne l'ampleur de la
  collecte.

---

## Ce qui reste à votre charge

Ces points ne relèvent pas du code : ils incombent à qui met l'instance en service.

### 1. Base légale du traitement

Vous n'avez pas le consentement des personnes recherchées. La base légale sera donc
l'**intérêt légitime** (article 6.1.f), qui doit être documenté par une mise en balance
écrite entre votre intérêt et les droits des personnes concernées.

Cette analyse doit exister sur papier avant la première vente.

### 2. Analyse d'impact (AIPD)

Une AIPD est très probablement **obligatoire** : le traitement croise des données
issues de sources multiples, à grande échelle, en vue d'identifier des personnes.
C'est un cas typique visé par l'article 35. Faites-la valider par un juriste ou un DPO.

### 3. Rôles : responsable de traitement ou sous-traitant

Deux situations, selon votre usage :

- **Vous installez l'outil pour vos propres recherches** (le cas courant) : vous
  définissez les finalités, vous êtes donc **responsable de traitement**. Il vous faut
  une base légale documentée et un registre des traitements.
- **Vous ouvrez votre instance à des tiers** qui mènent leurs propres recherches : ils
  sont responsables de traitement, vous êtes **sous-traitant**. S'y ajoutent un
  contrat de sous-traitance (article 28) avec chacun, des conditions d'utilisation
  interdisant explicitement les usages illicites, et la possibilité de suspendre un
  compte.

### 4. Information des personnes concernées

L'article 14 impose en principe d'informer les personnes dont les données sont
collectées indirectement. La dérogation de l'article 14.5.b (effort disproportionné)
est mobilisable, mais elle doit être **justifiée par écrit**, pas simplement supposée.

### 5. Hébergement

Vous hébergez l'instance : aucune donnée ne transite par un service tiers du projet.
Sur votre machine, rien à faire de plus. Sur un serveur, un hébergeur européen (OVH,
Scaleway, Hetzner) évite les questions de transfert hors Union et simplifie
considérablement le dossier de conformité. Évitez les services cloud américains, même
pour les sauvegardes.

### 6. Sécurité

Mesures déjà en place : mots de passe hachés en Argon2id, jetons en cookies `httpOnly`
révocables, cloisonnement par organisation, blocage après tentatives répétées.

À votre charge : TLS obligatoire, chiffrement des sauvegardes, plan de notification de
violation sous 72 heures.

---

## Points de vigilance sur l'usage

L'outil ne peut pas distinguer techniquement une enquête légitime d'un pistage
malveillant. Trois recommandations, par ordre d'importance :

1. **Vérifier l'identité professionnelle des clients** avant d'ouvrir un accès payant.
2. **Surveiller les usages atypiques** : volume anormal, recherches répétées sur la
   même cible, pseudonymes évoquant des personnes privées.
3. **Prévoir une procédure de signalement** permettant à une personne de demander la
   suppression de données la concernant, et de la traiter dans le mois.

Le journal d'accès rend ces contrôles possibles. Encore faut-il les exercer : c'est
précisément ce qu'un contrôle vous demandera de démontrer.
