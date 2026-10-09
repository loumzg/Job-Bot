"""Un cycle de recherche : sources -> filtres -> déduplication -> offres nouvelles -> export."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from job_bot.config import Config
from job_bot.filters import Criteria, apply_filters
from job_bot.geo import Place, resolve_city
from job_bot.models import JobOffer
from job_bot.report import ReportContext
from job_bot.sources import SERVER_SIDE_KEYWORDS, JobSource, SearchQuery, SourceError
from job_bot.storage import SeenStore, deduplicate, export

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    offers: list[JobOffer] = field(default_factory=list)
    fetched: int = 0
    exported: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def resolve_location(config: Config, offline: bool = False) -> Place | None:
    """Code INSEE + coordonnées de la ville configurée (``commune`` prime sur ``ville``)."""
    loc = config.location
    if loc.commune:
        return Place(name=loc.city or loc.commune, insee_code=loc.commune)
    if not loc.city or offline:
        return None
    place = resolve_city(loc.city)
    if place is None:
        log.warning("Ville %r introuvable : recherche sans localisation", loc.city)
    else:
        log.info("Ville %s -> code INSEE %s", place.name, place.insee_code)
    return place


def build_query(config: Config, place: Place | None) -> SearchQuery:
    s = config.search
    return SearchQuery(
        keywords=s.keywords,
        rome_codes=s.rome_codes,
        sectors=s.sectors,
        commune=place.insee_code if place else "",
        department=config.location.department,
        radius_km=config.location.radius_km,
        max_age_days=s.max_age_days,
        contract_types=s.contract_types,
        max_results=s.max_results,
    )


def build_criteria(config: Config, place: Place | None) -> Criteria:
    center = None
    if place and place.latitude is not None and place.longitude is not None:
        center = (place.latitude, place.longitude)
    return Criteria(
        keywords=config.search.keywords,
        rome_codes=config.search.rome_codes,
        sectors=config.search.sectors,
        contract_types=config.search.contract_types,
        exclusions=config.filters.exclusions,
        exclude_required_license=config.filters.exclude_required_license,
        scope=config.filters.scope,
        max_age_days=config.search.max_age_days,
        center=center,
        radius_km=float(config.location.radius_km) if center else None,
    )


def report_context(config: Config, place: Place | None, fetched: int | None = None) -> ReportContext:
    center = None
    if place and place.latitude is not None and place.longitude is not None:
        center = (place.latitude, place.longitude)
    loc = config.location
    where = place.name if place else loc.city or (f"département {loc.department}" if loc.department else "")
    return ReportContext(
        keywords=config.search.keywords,
        place=where,
        radius_km=loc.radius_km if place else None,
        center=center,
        fetched=fetched,
    )


def run_once(
    config: Config,
    sources: list[JobSource],
    store: SeenStore | None,
    *,
    place: Place | None = None,
    write: bool = True,
    now: datetime | None = None,
) -> RunResult:
    """Exécute un cycle. ``write=False`` : n'exporte rien et ne met pas à jour les offres vues."""
    result = RunResult()
    query = build_query(config, place)
    collected: list[JobOffer] = []
    for source in sources:
        try:
            batch = list(source.search(query))
        except SourceError as exc:
            log.error("%s", exc)
            result.errors.append(str(exc))
            continue
        log.info("Source %s : %d offres récupérées", source.name, len(batch))
        collected.extend(batch)
    result.fetched = len(collected)

    kept, rejected = apply_filters(collected, build_criteria(config, place), now, SERVER_SIDE_KEYWORDS)
    if rejected:
        log.info("Offres écartées : %s", ", ".join(f"{k}={v}" for k, v in sorted(rejected.items())))
    unique = deduplicate(kept)
    if store is not None and config.output.only_new:
        unique = store.filter_new(unique)
    unique.sort(key=lambda o: o.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    result.offers = unique
    log.info("%d offres retenues (%d récupérées)", len(unique), result.fetched)

    if write and unique:
        context = report_context(config, place, result.fetched)
        result.exported = export(unique, config.output.directory, config.output.formats, context=context)
        for path in result.exported:
            log.info("Export : %s", path)
    if write and store is not None:
        store.mark_seen(unique)
        store.save()
    return result


def run_forever(config: Config, cycle: Callable[[], object]) -> None:
    """Relance ``cycle`` toutes les ``interval_minutes`` minutes (Ctrl+C pour arrêter)."""
    interval = config.interval_minutes * 60
    log.info("Mode planifié : un cycle toutes les %d minutes (Ctrl+C pour arrêter)", config.interval_minutes)
    while True:
        started = time.monotonic()
        try:
            cycle()
        except Exception:  # un cycle raté ne doit pas arrêter la boucle
            log.exception("Erreur pendant le cycle")
        time.sleep(max(interval - (time.monotonic() - started), 0))
