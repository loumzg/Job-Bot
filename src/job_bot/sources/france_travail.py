"""Source principale : API officielle France Travail « Offres d'emploi v2 ».

Documentation : https://francetravail.io (catalogue > API Offres d'emploi).
Accès gratuit après inscription ; authentification OAuth2 « client credentials ».
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Iterator

import requests

from job_bot.models import JobOffer
from job_bot.sources.base import JobSource, SearchQuery, SourceError

log = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
TOKEN_REALM = "/partenaire"
SCOPE = "api_offresdemploiv2 o2dsoffre"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
OFFER_PAGE_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"

PAGE_SIZE = 150          # taille maximale d'une page (paramètre range)
MAX_RESULTS = 1150       # plafond prudent pour une même recherche
PUBLISHED_SINCE_VALUES = (1, 3, 7, 14, 31)  # valeurs usuelles de publieeDepuis
MAX_SECTORS_PER_QUERY = 2                   # secteurActivite : 2 valeurs max
MIN_INTERVAL_S = 0.15    # l'API limite à ~10 appels/s : on reste en dessous
TIMEOUT_S = 20


def published_since(max_age_days: int | None) -> int | None:
    """Plus petite valeur usuelle couvrant ``max_age_days`` (None si > 31 : filtrage local)."""
    if not max_age_days:
        return None
    for value in PUBLISHED_SINCE_VALUES:
        if max_age_days <= value:
            return value
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_offer(raw: dict[str, Any]) -> JobOffer:
    """Convertit une offre JSON de l'API en ``JobOffer`` (champs absents tolérés)."""
    lieu = raw.get("lieuTravail") or {}
    entreprise = raw.get("entreprise") or {}
    origine = raw.get("origineOffre") or {}
    offer_id = str(raw.get("id", ""))
    licenses = [
        p["libelle"]
        for p in raw.get("permis") or []
        if isinstance(p, dict) and p.get("libelle") and p.get("exigence", "E") == "E"
    ]
    return JobOffer(
        source=FranceTravailSource.name,
        id=offer_id,
        title=raw.get("intitule") or "",
        url=origine.get("urlOrigine") or OFFER_PAGE_URL.format(id=offer_id),
        company=entreprise.get("nom") or "",
        location=lieu.get("libelle") or "",
        description=raw.get("description") or "",
        published_at=_parse_datetime(raw.get("dateCreation")),
        contract_type=raw.get("typeContrat") or "",
        rome_code=raw.get("romeCode") or "",
        sector_code=str(raw.get("secteurActivite") or ""),
        sector_label=raw.get("secteurActiviteLibelle") or "",
        latitude=_to_float(lieu.get("latitude")),
        longitude=_to_float(lieu.get("longitude")),
        required_licenses=licenses,
    )


def parse_search_response(payload: dict[str, Any] | None) -> list[JobOffer]:
    """Extrait les offres d'une réponse de ``/offres/search``."""
    if not payload:
        return []
    return [parse_offer(r) for r in payload.get("resultats") or [] if isinstance(r, dict)]


class FranceTravailSource(JobSource):
    name = "france_travail"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        session: requests.Session | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise SourceError(
                "Identifiants France Travail manquants : renseigne FRANCE_TRAVAIL_CLIENT_ID "
                "et FRANCE_TRAVAIL_CLIENT_SECRET dans .env (voir README)."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._token: str | None = None
        self._token_expiry = 0.0
        self._last_call = 0.0

    # --- authentification -------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        try:
            resp = self._session.post(
                TOKEN_URL,
                params={"realm": TOKEN_REALM},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": SCOPE,
                },
                timeout=TIMEOUT_S,
            )
        except requests.RequestException as exc:
            raise SourceError(f"France Travail : échec de connexion ({exc})") from exc
        if resp.status_code != 200:
            raise SourceError(f"France Travail : authentification refusée (HTTP {resp.status_code})")
        data = resp.json()
        self._token = str(data["access_token"])
        self._token_expiry = time.monotonic() + max(int(data.get("expires_in", 1500)) - 60, 30)
        return self._token

    # --- appels -----------------------------------------------------------
    def _throttle(self) -> None:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get_page(self, params: dict[str, str]) -> tuple[list[JobOffer], bool]:
        """Renvoie (offres, il_en_reste)."""
        resp: requests.Response | None = None
        for attempt in range(3):
            self._throttle()
            headers = {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}
            try:
                resp = self._session.get(SEARCH_URL, params=params, headers=headers, timeout=TIMEOUT_S)
            except requests.RequestException as exc:
                raise SourceError(f"France Travail : erreur réseau ({exc})") from exc
            if resp.status_code == 429 and attempt < 2:
                delay = min(float(resp.headers.get("Retry-After", 2)), 30.0)
                log.warning("France Travail : limite de débit atteinte, pause de %.0f s", delay)
                time.sleep(delay)
                continue
            if resp.status_code == 401 and attempt < 2:
                self._token = None  # jeton expiré : on en redemande un
                continue
            break
        assert resp is not None
        if resp.status_code == 204:
            return [], False
        if resp.status_code not in (200, 206):
            raise SourceError(f"France Travail : HTTP {resp.status_code} - {resp.text[:200]}")
        return parse_search_response(resp.json()), resp.status_code == 206

    def build_params(self, query: SearchQuery) -> dict[str, str]:
        """Paramètres communs à toutes les pages (hors motsCles et range)."""
        params: dict[str, str] = {"sort": "1"}  # 1 = date de création décroissante
        if query.rome_codes:
            params["codeROME"] = ",".join(query.rome_codes)
        if query.sectors:
            if len(query.sectors) <= MAX_SECTORS_PER_QUERY:
                params["secteurActivite"] = ",".join(query.sectors)
            else:
                log.info("Plus de %d secteurs : filtrage des secteurs fait localement", MAX_SECTORS_PER_QUERY)
        if query.commune:
            params["commune"] = query.commune
            if query.radius_km is not None:
                params["distance"] = str(query.radius_km)
        elif query.department:
            params["departement"] = query.department
        if query.contract_types:
            params["typeContrat"] = ",".join(query.contract_types)
        since = published_since(query.max_age_days)
        if since:
            params["publieeDepuis"] = str(since)
        return params

    def search(self, query: SearchQuery) -> Iterator[JobOffer]:
        base = self.build_params(query)
        limit = min(query.max_results, MAX_RESULTS)
        keywords: list[str | None] = [k.strip() for k in query.keywords if len(k.strip()) >= 2] or [None]
        for keyword in keywords:  # une recherche par mot-clé, fusionnées ensuite
            fetched = 0
            while fetched < limit:
                params = dict(base)
                if keyword:
                    params["motsCles"] = keyword
                params["range"] = f"{fetched}-{min(fetched + PAGE_SIZE, limit) - 1}"
                offers, more = self._get_page(params)
                log.debug("France Travail %r [%s] : %d offres", keyword, params["range"], len(offers))
                yield from offers
                fetched += len(offers)
                if not more or not offers:
                    break
