# Job-Bot

Outil en ligne de commande pour **simplifier la recherche d'emploi dans le développement
web** : il interroge des sources d'offres légitimes, ne garde que les **métiers du
développement web** (développeur web, front-end, back-end, full stack, développeur IA /
agents, intégrateur web, webmaster…), les **filtre par métier, mots-clés, lieu et date**,
supprime les doublons, mémorise ce qui a déjà été vu et exporte le résultat en CSV, JSON
ou en **rapport HTML** autonome, lisible et filtrable dans un navigateur.

> Job-Bot **ne postule pas** à votre place et ne contourne aucune protection anti-robot.
> Il vous aide à trouver les offres pertinentes ; la candidature reste une démarche humaine.

## Sommaire

- [Sources supportées](#sources-supportées)
- [Installation](#installation)
- [Obtenir les identifiants France Travail](#obtenir-les-identifiants-france-travail)
- [Configuration](#configuration)
- [Exemples d'usage](#exemples-dusage)
- [Rapport HTML](#rapport-html)
- [Périmètre : développement web](#périmètre--développement-web)
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
mots_cles = ["développeur web", "développeur full stack", "développeur ia", "webmaster"]
codes_rome = ["M1805", "E1101"]  # préfixes acceptés, ex. ["M18"]
secteurs = []              # divisions NAF à 2 chiffres, ex. ["47"]
types_contrat = []         # ex. ["CDI", "CDD"]
publiee_depuis_jours = 7

[localisation]
ville = "Paris"            # ou commune = "75056" (code INSEE), ou departement = "75"
rayon_km = 10

[filtres]
perimetre = "dev_web"      # ou "aucun" pour désactiver le périmètre métier
exclusions = ["stage non remunere"]
exclure_permis_exige = false

[sources]
actives = ["france_travail"]

[sortie]
dossier = "output"
formats = ["csv", "json"]  # et/ou "html"
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
job-bot -k "développeur react,développeur typescript" --ville Lille --rayon 20 --contrat CDI,CDD --depuis 3

# Par métier (codes ROME) et secteur (NAF), export JSON uniquement
job-bot --rome M1805 --secteurs 62 --departement 33 -f json

# Sans le périmètre développement web (autres métiers, mots-clés libres)
job-bot --perimetre aucun --rome "" -k "data engineer"

# Exports CSV + rapport HTML horodatés dans output/
job-bot -f csv,html

# Démo hors ligne : rapport HTML écrit à un chemin précis (seul fichier créé)
job-bot --dry-run --ville Lyon --rapport rapport.html

# Écarter les offres qui exigent un permis, ajouter un flux RSS
job-bot --sans-permis --rss https://exemple.org/offres.rss

# Mode planifié : une recherche toutes les 2 heures (Ctrl+C pour arrêter)
job-bot --boucle --intervalle 120

# Sans installation du script : python -m job_bot --help
```

Sorties (toutes ignorées par git) :

- `output/offres_AAAAMMJJ-HHMMSS.csv` / `.json` / `.html` : offres retenues,
  uniquement si de nouvelles offres ont été trouvées (CSV séparé par `;`, encodé pour
  Excel ; HTML : voir [Rapport HTML](#rapport-html)) ;
- `output/seen_jobs.json` : offres déjà vues (`--toutes` pour les réafficher) ;
- `logs/job_bot.log` : journal avec rotation.

## Rapport HTML

Le format `html` (ou l'option `--rapport FICHIER`) produit **un seul fichier**, sans
dépendance à installer, qui s'ouvre d'un double-clic :

- **en tête, une grille de chiffres clés** : nombre d'offres, rythme de publication,
  répartition par source, par type de contrat, par ville, et mots les plus fréquents
  (petits graphiques SVG intégrés) ;
- **des cartes d'offres** : intitulé, entreprise, lieu (et distance si la ville de
  recherche est connue), contrat, date, mots-clés correspondants surlignés, lien vers
  l'annonce ;
- **recherche instantanée, filtres** (contrat, ville, source) **et tri** (pertinence,
  date, distance, entreprise) ; `/` place le curseur dans la recherche ;
- thème **clair / sombre** (suit le système, bascule mémorisée), animations discrètes
  désactivées si le système demande de réduire les animations, mise en page pensée
  pour le téléphone.

Direction artistique « outil de développeur » : gris froid très clair (nuit bleutée en
sombre) et accent **ultraviolet** (`#5a3dd8` en clair, `#a898ff` en sombre), titres et
texte en *Bricolage Grotesque*, données (dates, compteurs, sources) en *JetBrains Mono*,
chiffres tabulaires. Toutes les couleurs sont des variables CSS et chaque couleur de texte
dépasse un contraste de 4,5:1 dans les deux thèmes (Google Fonts est la seule ressource
externe ; sans connexion, des polices système prennent le relais). Le pied de page
crédite l'auteur (« Créé par loun3s », lien vers son profil GitHub).

Sécurité : tout le texte des offres est échappé (`html.escape`), les données lues par le
script sont injectées en JSON neutralisé, seuls les liens `http(s)` sont conservés, et
une politique CSP n'autorise que les deux scripts du rapport (empreintes SHA-256).

| Ordinateur (thème clair) | Téléphone (thème sombre) |
|---|---|
| ![Rapport HTML sur ordinateur](docs/rapport-desktop.png) | ![Rapport HTML sur téléphone](docs/rapport-mobile.png) |

Dans le terminal, le résumé affiche un tableau aligné sur la largeur de la fenêtre,
coloré sobrement ; les couleurs sont coupées si la sortie n'est pas un terminal ou si
`NO_COLOR` est défini (`FORCE_COLOR` les force).

## Périmètre : développement web

Par défaut, Job-Bot ne retient que les offres de **développement web** :

| Famille | Exemples d'intitulés retenus |
|---|---|
| Web, front-end, back-end, full stack | Développeur web, Développeuse Front-End, Dév back-end, Développeur·euse fullstack |
| Langages et frameworks web | Développeur JavaScript / TypeScript / React / Vue / Angular / Node.js / PHP / Symfony / Laravel / WordPress / Django |
| IA appliquée | Développeur IA, développeur agentique, ingénieur IA (agents, LLM, RAG, intégration d'IA) |
| Intégration et webmastering | Intégrateur·rice web, webmaster, webmestre |

- **Mots-clés par défaut** (une recherche API chacun) : `développeur web`,
  `développeur front end`, `développeur back end`, `développeur full stack`,
  `développeur javascript`, `développeur php`, `développeur ia`, `intégrateur web`,
  `webmaster`.
- **Codes ROME par défaut** : `M1805` (Études et développement informatique, la fiche des
  développeurs) et `E1101` (Animation de site multimédia, rattachée aux webmasters et
  intégrateurs web par la certification RNCP « Webmaster »). `M1806` n'est pas retenu :
  c'est la fiche « Conseil et maîtrise d'ouvrage en systèmes d'information ».
- **Filtre de périmètre** (`perimetre = "dev_web"`, appliqué à toutes les sources, y
  compris France Travail) : l'intitulé doit nommer un rôle de développement
  (développeur, programmeur, intégrateur, webmaster, ingénieur logiciel / IA…) et une
  technologie web doit apparaître dans l'intitulé ou dans la description (React,
  PHP, API REST, LLM…). Le mot « web » seul dans une description ne suffit pas
  (« consultez notre site web »).
- **Faux positifs écartés** d'après l'intitulé : développeur commercial / d'affaires,
  business developer, chargé de développement, développement durable, développeur
  immobilier ou de projets éoliens, technicien réseau / support, helpdesk, data analyst,
  embarqué, firmware, COBOL / mainframe.
- **Variantes tolérées** : casse, accents et écritures courantes sont unifiées avant
  comparaison (« dév » = « développeur » = « développeuse » = « développeur·euse »,
  « full stack » = « full-stack » = « fullstack », « front » / « frontend » / « front-end »,
  « intégratrice » = « intégrateur », « webmestre » = « webmaster », « Node.js » = « nodejs »).

Les offres écartées sont comptées dans le journal (`périmètre=…`). `perimetre = "aucun"`
(ou `--perimetre aucun`) désactive ce filtre pour revenir à une recherche généraliste.

## Fonctionnement des filtres

Les critères sont envoyés à la source quand elle sait les traiter (cas de France
Travail), puis **réappliqués localement** sur toutes les sources :

- **périmètre** métier (voir ci-dessus) ;
- **mots-clés** : une offre est gardée si elle contient tous les mots d'au moins un
  mot-clé, sans tenir compte des accents, majuscules, ponctuation et variantes
  (« developpeur full stack » trouve « Développeuse Full-Stack » ; les mots de trois
  lettres ou moins, comme « ia » ou « php », doivent apparaître en entier). Pour France Travail, la recherche par
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
├── perimetre.py        # périmètre « développement web » (rôles, technologies, faux positifs)
├── storage.py          # déduplication, offres déjà vues, exports CSV/JSON/HTML
├── report.py           # rapport HTML (chiffres clés, cartes, échappement)
├── console.py          # résumé terminal (tableau aligné, couleurs ANSI)
├── templates/          # CSS et JS intégrés au rapport HTML
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

Les tests couvrent le périmètre développement web (chaque famille de métiers acceptée,
faux positifs rejetés, variantes d'écriture), les filtres, la déduplication, la mémorisation, les exports, le
parsing d'une réponse France Travail simulée, la pagination, le RSS/Atom, la CLI, le
rapport HTML (structure, échappement, CSP) et le résumé terminal.
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

Job-Bot is a small CLI that **searches and filters web development job offers**
(web / front-end / back-end / full stack developers, applied-AI and agent developers,
web integrators, webmasters; false positives such as "business developer" are dropped)
by keywords, occupation
codes (ROME), industry sectors (NAF), location/radius, contract type and publication date.
Its main source is the official, free **France Travail "Offres d'emploi v2" API**
(OAuth2 client credentials, register at francetravail.io); RSS/Atom feeds and local JSON
files are also supported through a pluggable `JobSource` interface. Results are
deduplicated, remembered across runs and exported to CSV/JSON or to a self-contained,
filterable HTML report (light/dark, mobile-friendly). It can run once or on a
schedule (15 min minimum). It does **not** auto-apply to jobs nor bypass anti-bot measures.

```bash
pip install -e ".[dev]" && pytest
job-bot --dry-run            # offline demo with fictitious offers
job-bot -k "développeur react" --ville Lyon --rayon 20
```

License: MIT.
