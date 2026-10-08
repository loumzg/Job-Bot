from __future__ import annotations

from datetime import datetime, timezone

from conftest import make_offer
from job_bot.filters import (
    Criteria,
    apply_filters,
    is_excluded,
    is_recent,
    matches_contract,
    matches_keywords,
    matches_sector,
    within_radius,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def test_keywords_ignore_accents_and_case() -> None:
    offer = make_offer(title="Employé ADMINISTRATIF", description="")
    assert matches_keywords(offer, ["employe administratif"])
    assert matches_keywords(offer, ["comptable", "administratif"])
    assert not matches_keywords(offer, ["comptable"])
    assert matches_keywords(offer, [])


def test_keywords_match_all_words_ignoring_punctuation() -> None:
    offer = make_offer(title="Agent d'accueil H/F", description="")
    assert matches_keywords(offer, ["agent accueil"])
    assert not matches_keywords(offer, ["agent entretien"])


def test_keywords_search_description() -> None:
    offer = make_offer(title="Poste", description="Préparation de commandes en entrepôt")
    assert matches_keywords(offer, ["preparation de commandes"])


def test_exclusions() -> None:
    offer = make_offer(description="Permis B obligatoire, véhicule fourni")
    assert is_excluded(offer, ["permis b obligatoire"])
    assert not is_excluded(offer, ["temps partiel"])
    assert not is_excluded(offer, [""])


def test_exclude_required_license() -> None:
    with_license = make_offer(required_licenses=["B - Véhicule léger Exigé"])
    assert is_excluded(with_license, [], exclude_required_license=True)
    assert not is_excluded(make_offer(), [], exclude_required_license=True)
    assert is_excluded(with_license, ["vehicule leger exige"])


def test_sector_by_rome_prefix_and_naf_division() -> None:
    offer = make_offer(rome_code="M1805", sector_code="62")
    assert matches_sector(offer, ["M18"], [])
    assert matches_sector(offer, ["m1805"], ["62"])
    assert not matches_sector(offer, ["D1106"], [])
    assert not matches_sector(offer, [], ["47"])
    assert matches_sector(offer, [], ["62.01Z"])  # code NAF complet ramené à la division


def test_sector_kept_when_information_missing() -> None:
    assert matches_sector(make_offer(), ["M1805"], ["62"])


def test_contract() -> None:
    assert matches_contract(make_offer(contract_type="CDI"), ["cdi", "CDD"])
    assert not matches_contract(make_offer(contract_type="MIS"), ["CDI"])
    assert matches_contract(make_offer(), ["CDI"])


def test_recent() -> None:
    old = make_offer(published_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert not is_recent(old, 7, NOW)
    assert is_recent(old, None, NOW)
    assert is_recent(make_offer(published_at=datetime(2026, 10, 6)), 7, NOW)  # date naïve = UTC
    assert is_recent(make_offer(published_at=None), 7, NOW)


def test_radius() -> None:
    paris = (48.8566, 2.3522)
    versailles = make_offer(latitude=48.8049, longitude=2.1204)  # ~17 km
    assert within_radius(versailles, paris, 20)
    assert not within_radius(versailles, paris, 10)
    assert within_radius(make_offer(), paris, 10)  # sans coordonnées : conservée
    assert within_radius(versailles, None, 10)


def test_apply_filters_counts_rejections() -> None:
    offers = [
        make_offer(id="ok", title="Vendeur polyvalent"),
        make_offer(id="kw", title="Boulanger"),
        make_offer(id="ex", title="Vendeur itinérant", description="Permis B obligatoire"),
        make_offer(id="old", title="Vendeur", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    criteria = Criteria(keywords=["vendeur"], exclusions=["permis b obligatoire"], max_age_days=30)
    kept, rejected = apply_filters(offers, criteria, NOW)
    assert [o.id for o in kept] == ["ok"]
    assert rejected == {"mots-clés": 1, "exclusion": 1, "date": 1}


def test_apply_filters_skips_keywords_for_server_side_sources() -> None:
    offer = make_offer(source="france_travail", title="Conseiller de vente")
    kept, _ = apply_filters([offer], Criteria(keywords=["vendeur"]), NOW, frozenset({"france_travail"}))
    assert kept == [offer]
