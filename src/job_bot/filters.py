"""Filtres appliqués localement à toutes les offres, quelle que soit la source.

Règle générale : une offre n'est rejetée sur un critère que si elle porte
l'information correspondante (une offre RSS sans code ROME n'est pas rejetée
par le filtre « codes ROME »).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from job_bot.geo import haversine_km
from job_bot.models import JobOffer, normalize_text


@dataclass(slots=True)
class Criteria:
    keywords: list[str] = field(default_factory=list)
    rome_codes: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    contract_types: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    exclude_required_license: bool = False
    max_age_days: int | None = None
    center: tuple[float, float] | None = None
    radius_km: float | None = None


def matches_keywords(offer: JobOffer, keywords: Iterable[str]) -> bool:
    """Vrai si l'offre contient tous les mots d'au moins un des mots-clés.

    Comparaison sans accents, casse ni ponctuation : « agent accueil » trouve
    « Agent d'accueil », « commande » trouve « commandes ».
    """
    wanted = [normalize_text(k).split() for k in keywords]
    wanted = [words for words in wanted if words]
    if not wanted:
        return True
    text = offer.searchable_text()
    return any(all(w in text for w in words) for words in wanted)


def is_excluded(offer: JobOffer, exclusions: Iterable[str], exclude_required_license: bool = False) -> bool:
    """Vrai si l'offre contient une expression exclue (ou exige un permis, si demandé)."""
    if exclude_required_license and offer.required_licenses:
        return True
    text = offer.searchable_text()
    return any(normalize_text(e) in text for e in exclusions if e.strip())


def matches_sector(offer: JobOffer, rome_codes: Iterable[str], sectors: Iterable[str]) -> bool:
    """Codes ROME par préfixe (ex. « M18 » couvre « M1805 ») et secteurs NAF par division (2 chiffres)."""
    rome = [c.upper() for c in rome_codes]
    if rome and offer.rome_code and not any(offer.rome_code.upper().startswith(c) for c in rome):
        return False
    divisions = [s.strip()[:2] for s in sectors if s.strip()]
    if divisions and offer.sector_code and offer.sector_code[:2] not in divisions:
        return False
    return True


def matches_contract(offer: JobOffer, contract_types: Iterable[str]) -> bool:
    wanted = {c.upper() for c in contract_types}
    return not wanted or not offer.contract_type or offer.contract_type.upper() in wanted


def is_recent(offer: JobOffer, max_age_days: int | None, now: datetime | None = None) -> bool:
    if not max_age_days or offer.published_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    published = offer.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return now - published <= timedelta(days=max_age_days)


def within_radius(offer: JobOffer, center: tuple[float, float] | None, radius_km: float | None) -> bool:
    if center is None or radius_km is None or offer.latitude is None or offer.longitude is None:
        return True
    return haversine_km(center[0], center[1], offer.latitude, offer.longitude) <= radius_km


def apply_filters(
    offers: Iterable[JobOffer],
    criteria: Criteria,
    now: datetime | None = None,
    skip_keywords_for: frozenset[str] = frozenset(),
) -> tuple[list[JobOffer], Counter[str]]:
    """Filtre les offres ; renvoie (offres retenues, compteur des motifs de rejet).

    ``skip_keywords_for`` : sources dont la recherche par mots-clés est déjà faite
    côté serveur (l'API peut trouver des synonymes absents du texte).
    """
    kept: list[JobOffer] = []
    rejected: Counter[str] = Counter()
    for offer in offers:
        if offer.source not in skip_keywords_for and not matches_keywords(offer, criteria.keywords):
            rejected["mots-clés"] += 1
        elif is_excluded(offer, criteria.exclusions, criteria.exclude_required_license):
            rejected["exclusion"] += 1
        elif not matches_sector(offer, criteria.rome_codes, criteria.sectors):
            rejected["secteur"] += 1
        elif not matches_contract(offer, criteria.contract_types):
            rejected["contrat"] += 1
        elif not is_recent(offer, criteria.max_age_days, now):
            rejected["date"] += 1
        elif not within_radius(offer, criteria.center, criteria.radius_km):
            rejected["distance"] += 1
        else:
            kept.append(offer)
    return kept, rejected
