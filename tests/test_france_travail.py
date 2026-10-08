"""Source France Travail testée avec une session HTTP factice (aucun appel réseau)."""

from __future__ import annotations

from typing import Any

import pytest

from job_bot.sources import SearchQuery, SourceError
from job_bot.sources.france_travail import (
    SCOPE,
    SEARCH_URL,
    TOKEN_URL,
    FranceTravailSource,
    parse_search_response,
    published_since,
)


class FakeResponse:
    def __init__(self, status: int, payload: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = "" if payload is None else str(payload)

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Rejoue des réponses préparées et enregistre les requêtes."""

    def __init__(self, pages: list[FakeResponse]) -> None:
        self.pages = list(pages)
        self.token_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        assert url == TOKEN_URL
        self.token_calls.append(kwargs)
        return FakeResponse(200, {"access_token": "tok", "expires_in": 1499})

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        assert url == SEARCH_URL
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        self.search_calls.append(kwargs["params"])
        return self.pages.pop(0)


def test_parse_search_response(ft_payload: dict[str, Any]) -> None:
    offers = parse_search_response(ft_payload)
    assert [o.id for o in offers] == ["100AAAA", "100BBBB", "100CCCC"]

    dev = offers[0]
    assert dev.source == "france_travail"
    assert dev.title == "Développeur Python H/F"
    assert dev.company == "Exemple SAS"
    assert dev.location == "33 - BORDEAUX"
    assert dev.rome_code == "M1805"
    assert dev.sector_code == "62"
    assert dev.contract_type == "CDI"
    assert dev.published_at is not None and dev.published_at.year == 2026 and dev.published_at.tzinfo
    assert dev.latitude == pytest.approx(44.8378)
    assert dev.url.endswith("/100AAAA")

    driver = offers[1]
    assert driver.required_licenses == ["B - Véhicule léger Exigé"]  # le permis « souhaité » est ignoré
    assert driver.latitude == pytest.approx(44.84)  # coordonnées en chaîne acceptées
    assert driver.company == ""

    minimal = offers[2]
    assert minimal.url == "https://candidat.francetravail.fr/offres/recherche/detail/100CCCC"
    assert minimal.published_at is None


def test_parse_empty_payload() -> None:
    assert parse_search_response(None) == []
    assert parse_search_response({}) == []


@pytest.mark.parametrize(("days", "expected"), [(None, None), (0, None), (1, 1), (2, 3), (7, 7), (10, 14), (31, 31), (60, None)])
def test_published_since(days: int | None, expected: int | None) -> None:
    assert published_since(days) == expected


def test_search_builds_params_and_paginates(ft_payload: dict[str, Any]) -> None:
    session = FakeSession([FakeResponse(206, ft_payload), FakeResponse(200, {"resultats": []})])
    source = FranceTravailSource("id", "secret", session=session)  # type: ignore[arg-type]
    query = SearchQuery(
        keywords=["python"], rome_codes=["M1805"], sectors=["62"], commune="33063",
        radius_km=20, max_age_days=5, contract_types=["CDI"], max_results=300,
    )
    offers = list(source.search(query))

    assert len(offers) == 3
    assert session.token_calls[0]["data"]["scope"] == SCOPE
    assert session.token_calls[0]["params"] == {"realm": "/partenaire"}
    first, second = session.search_calls
    assert first == {
        "sort": "1", "codeROME": "M1805", "secteurActivite": "62", "commune": "33063",
        "distance": "20", "typeContrat": "CDI", "publieeDepuis": "7", "motsCles": "python", "range": "0-149",
    }
    assert second["range"] == "3-152"  # reprend après les offres déjà reçues
    assert len(session.token_calls) == 1  # jeton réutilisé


def test_search_one_request_per_keyword_and_204() -> None:
    session = FakeSession([FakeResponse(204), FakeResponse(204)])
    source = FranceTravailSource("id", "secret", session=session)  # type: ignore[arg-type]
    assert list(source.search(SearchQuery(keywords=["vendeur", "caissier", "x"], department="75"))) == []
    assert [c["motsCles"] for c in session.search_calls] == ["vendeur", "caissier"]  # « x » < 2 caractères
    assert session.search_calls[0]["departement"] == "75"


def test_too_many_sectors_are_filtered_locally() -> None:
    source = FranceTravailSource("id", "secret", session=FakeSession([]))  # type: ignore[arg-type]
    assert "secteurActivite" not in source.build_params(SearchQuery(sectors=["47", "62", "52"]))


def test_http_error_raises_source_error() -> None:
    session = FakeSession([FakeResponse(400, {"message": "bad"})])
    source = FranceTravailSource("id", "secret", session=session)  # type: ignore[arg-type]
    with pytest.raises(SourceError, match="HTTP 400"):
        list(source.search(SearchQuery()))


def test_missing_credentials() -> None:
    with pytest.raises(SourceError, match="Identifiants"):
        FranceTravailSource("", "")
