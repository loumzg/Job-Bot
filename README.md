# Job-Bot

Outil en ligne de commande pour **simplifier la recherche d'emploi** : il interroge des
sources d'offres légitimes, les **filtre par secteur, métier, mots-clés, lieu et date**,
supprime les doublons, mémorise ce qui a déjà été vu et exporte le résultat en CSV / JSON.

> Job-Bot **ne postule pas** à votre place et ne contourne aucune protection anti-robot.
> Il vous aide à trouver les offres pertinentes ; la candidature reste une démarche humaine.

## Sommaire

- [Sources supportées](#sources-supportées)
- [Installation](#installation)
- [Obtenir les identifiants France Travail](#obtenir-les-identifiants-france-travail)
- [Configuration](#configuration)
- [Exemples d'usage](#exemples-dusage)
- [Fonctionnement des filtres](#fonctionnement-des-filtres)
- [Architecture](#architecture)
- [Tests](#tests)
- [Usage responsable](#usage-responsable)
- [English summary](#english-summary)

## Sources supportées

| Source | Nom | Description |
|---|---|---|
| API France Travail « Offres d'emploi v2 » | `france_travail` | **Source principale.** API officielle et gratuite (inscription requise). |
| Flux RSS 2.0 / Atom | `rss` | Tout flux public d'offres (sites carrières, job boards qui en publient). |
| Fichier JSON local | `fixture` | Fichier au format de l'API France Travail ; sert au mode `--dry-run` (des offres **fictives** sont fournies). |

Les sources sont **pluggables** : chacune implémente la même interface (`JobSource.search`),
voir [Architecture](#architecture).

### Détails techniques de l'API France Travail

| Élément | Valeur utilisée |
|---|---|
| Jeton OAuth2 (client credentials) | `POST https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire` |
| Scope | `api_offresdemploiv2 o2dsoffre` |
| Recherche | `GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search` |
| Paramètres envoyés | `motsCles`, `codeROME`, `secteurActivite`, `commune` + `distance` ou `departement`, `typeContrat`, `publieeDepuis`, `sort=1`, `range` |
| Pagination | `range=début-fin`, 150 offres max par page ; réponse `206` = d'autres pages, `204` = aucune offre |

État de vérification :

- **Vérifié en direct** : l'URL du jeton répond `400 invalid_client` à des identifiants
  bidons, l'URL de recherche répond `401` sans jeton : les deux endpoints existent bien.
- **Non vérifié avec de vrais identifiants** : le portail de documentation
  (francetravail.io) est une application JavaScript qui n'a pas pu être lue
  automatiquement. Les noms de paramètres, les limites (2 secteurs max, `publieeDepuis`
  parmi 1/3/7/14/31, plafond d'environ 1150 résultats par recherche) et les champs de
  réponse (`resultats`, `intitule`, `lieuTravail`, `romeCode`, `secteurActivite`,
  `permis`, `origineOffre.urlOrigine`…) proviennent de clients open source de l'API qui
  concordent entre eux. Au premier lancement réel, comparez avec la documentation
  officielle ; en cas d'écart, tout est centralisé dans
  `src/job_bot/sources/france_travail.py`.
- Pour Paris, Lyon et Marseille, l'API attend peut-être les codes INSEE
  d'arrondissement plutôt que celui de la commune : à vérifier, sinon utilisez
  `departement`.

## Installation

Python 3.11 ou plus récent.

```bash
git clone https://github.com/loumzg/Job-Bot.git
cd Job-Bot
python -m venv .venv
# Windows : .venv\Scripts\activate    —    Linux / macOS : source .venv/bin/activate
pip install -e .            # ou : pip install -e ".[dev]" pour lancer les tests
cp config.example.toml config.toml   # Windows : copy config.example.toml config.toml
cp .env.example .env                 # Windows : copy .env.example .env
```

Seule dépendance : `requests`.

## Obtenir les identifiants France Travail

1. Créez un compte sur [francetravail.io](https://francetravail.io) (espace développeur).
2. Créez une application (« Mes applications »).
3. Abonnez-la à l'API **« Offres d'emploi »** (v2).
4. Copiez l'**identifiant client** et la **clé secrète** dans `.env` :

   ```dotenv
   FRANCE_TRAVAIL_CLIENT_ID=votre_identifiant
   FRANCE_TRAVAIL_CLIENT_SECRET=votre_cle_secrete
   ```

Le fichier `.env` est ignoré par git : **ne le commitez jamais**. Les variables
d'environnement déjà définies ont priorité sur `.env`.

(Les libellés exacts du portail peuvent varier légèrement.)

## Configuration

Tout se règle dans `config.toml` (copie commentée de [`config.example.toml`](config.example.toml)) :

```toml
[recherche]
mots_cles = ["preparateur de commandes", "agent accueil"]
codes_rome = []            # ex. ["N1103", "M18"]
secteurs = []              # divisions NAF à 2 chiffres, ex. ["47"]
types_contrat = []         # ex. ["CDI", "CDD"]
publiee_depuis_jours = 7

[localisation]
ville = "Paris"            # ou commune = "75056" (code INSEE), ou departement = "75"
rayon_km = 10

[filtres]
exclusions = ["permis b obligatoire", "vehicule obligatoire"]
exclure_permis_exige = false

[sources]
actives = ["france_travail"]

[sortie]
dossier = "output"
formats = ["csv", "json"]
seulement_nouvelles = true

[planification]
intervalle_minutes = 60    # mode --boucle, 15 minutes minimum
```

Le nom de ville est converti en code INSEE grâce à l'API publique
[geo.api.gouv.fr](https://geo.api.gouv.fr) (sans clé). Chaque option peut être
surchargée en ligne de commande : `job-bot --help`.

## Exemples d'usage

```bash
# Essai hors ligne, sans identifiants : offres fictives, rien n'est écrit
job-bot --dry-run

# Recherche unique avec config.toml
job-bot

# Surcharger la config : mots-clés, ville, rayon, contrats, offres des 3 derniers jours
job-bot -k "vendeur,caissier" --ville Lille --rayon 20 --contrat CDI,CDD --depuis 3

# Par métier (codes ROME) et secteur (NAF), export JSON uniquement
job-bot --rome M1805,M1806 --secteurs 62 --departement 33 -f json

# Écarter les offres qui exigent un permis, ajouter un flux RSS
job-bot --sans-permis --rss https://exemple.org/offres.rss

# Mode planifié : une recherche toutes les 2 heures (Ctrl+C pour arrêter)
job-bot --boucle --intervalle 120

# Sans installation du script : python -m job_bot --help
```

Sorties (toutes ignorées par git) :

- `output/offres_AAAAMMJJ-HHMMSS.csv` / `.json` : offres retenues, uniquement si
  de nouvelles offres ont été trouvées (CSV séparé par `;`, encodé pour Excel) ;
- `output/seen_jobs.json` : offres déjà vues (`--toutes` pour les réafficher) ;
- `logs/job_bot.log` : journal avec rotation.

## Fonctionnement des filtres

Les critères sont envoyés à la source quand elle sait les traiter (cas de France
Travail), puis **réappliqués localement** sur toutes les sources :

- **mots-clés** : une offre est gardée si elle contient tous les mots d'au moins un
  mot-clé, sans tenir compte des accents, majuscules et ponctuation
  (« agent accueil » trouve « Agent d'accueil »). Pour France Travail, la recherche par
  mots-clés est faite par l'API (qui gère les synonymes) et n'est pas refiltrée ;
- **codes ROME** par préfixe (`M18` couvre `M1805`) et **secteurs** par division NAF ;
- **exclusions** : expressions recherchées dans l'intitulé, la description et les
  permis exigés ;
- **date** de publication et **rayon** (si l'offre fournit ses coordonnées) ;
- une offre n'est jamais rejetée sur une information qu'elle ne fournit pas (une
  offre RSS sans code ROME passe le filtre ROME) ;
- **déduplication** par identifiant, puis par intitulé + entreprise + lieu (même
  offre publiée sur plusieurs sources).

## Architecture

```
src/job_bot/
├── cli.py              # arguments, logs, mode unique / planifié
├── config.py           # lecture de config.toml et de .env, validation
├── runner.py           # un cycle : sources -> filtres -> dédup -> export
├── filters.py          # filtres purs, testés unitairement
├── storage.py          # déduplication, offres déjà vues, exports CSV/JSON
├── geo.py              # ville -> code INSEE, distance
├── models.py           # JobOffer, modèle commun à toutes les sources
├── data/demo_offres.json
└── sources/
    ├── base.py         # interface JobSource + SearchQuery
    ├── france_travail.py
    ├── rss.py
    └── fixture.py
```

Ajouter une source : créer une sous-classe de `JobSource` dont la méthode
`search(query)` renvoie des `JobOffer`, puis la déclarer dans
`sources/__init__.py` (`build_sources`) et dans `KNOWN_SOURCES` (`config.py`).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Les tests couvrent les filtres, la déduplication, la mémorisation, les exports, le
parsing d'une réponse France Travail simulée, la pagination, le RSS/Atom et la CLI.
**Aucun appel réseau** : un garde-fou fait échouer tout test qui tenterait d'en ouvrir un.

## Usage responsable

- Utilisez des **sources officielles ou explicitement publiques** ; respectez leurs
  conditions d'utilisation (pour France Travail : quotas d'appels et conditions de
  réutilisation et d'affichage des offres).
- Gardez un **intervalle raisonnable** : le mode planifié impose 15 minutes minimum,
  et une recherche par heure suffit largement.
- N'ajoutez pas de source qui scrape un site interdisant l'extraction automatique ou
  qui contourne un CAPTCHA.
- Vos identifiants restent dans `.env`, hors du dépôt.

Ce projet est fourni à des fins éducatives, sans garantie (voir [LICENSE](LICENSE)).
L'utilisateur reste responsable du respect des lois et des conditions d'utilisation des
services interrogés.

## English summary

Job-Bot is a small CLI that **searches and filters job offers** by keywords, occupation
codes (ROME), industry sectors (NAF), location/radius, contract type and publication date.
Its main source is the official, free **France Travail "Offres d'emploi v2" API**
(OAuth2 client credentials, register at francetravail.io); RSS/Atom feeds and local JSON
files are also supported through a pluggable `JobSource` interface. Results are
deduplicated, remembered across runs and exported to CSV/JSON. It can run once or on a
schedule (15 min minimum). It does **not** auto-apply to jobs nor bypass anti-bot measures.

```bash
pip install -e ".[dev]" && pytest
job-bot --dry-run            # offline demo with fictitious offers
job-bot -k "data analyst" --ville Lyon --rayon 20
```

License: MIT.
