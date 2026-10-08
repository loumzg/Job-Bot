"""Chargement de la configuration (fichier TOML + variables d'environnement)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_INTERVAL_MINUTES = 15
KNOWN_SOURCES = ("france_travail", "rss", "fixture")
KNOWN_FORMATS = ("csv", "json")


class ConfigError(ValueError):
    """Configuration invalide."""


@dataclass(slots=True)
class SearchConfig:
    keywords: list[str] = field(default_factory=list)
    rome_codes: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    contract_types: list[str] = field(default_factory=list)
    max_age_days: int | None = 7
    max_results: int = 150


@dataclass(slots=True)
class LocationConfig:
    city: str = ""
    commune: str = ""
    department: str = ""
    radius_km: int = 10


@dataclass(slots=True)
class FilterConfig:
    exclusions: list[str] = field(default_factory=list)
    exclude_required_license: bool = False


@dataclass(slots=True)
class OutputConfig:
    directory: Path = Path("output")
    formats: list[str] = field(default_factory=lambda: ["csv"])
    seen_file: Path = Path("output/seen_jobs.json")
    only_new: bool = True
    log_file: Path = Path("logs/job_bot.log")


@dataclass(slots=True)
class Config:
    search: SearchConfig = field(default_factory=SearchConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    sources: list[str] = field(default_factory=lambda: ["france_travail"])
    rss_urls: list[str] = field(default_factory=list)
    fixture_path: Path | None = None
    interval_minutes: int = 60

    def validate(self) -> None:
        unknown = [s for s in self.sources if s not in KNOWN_SOURCES]
        if unknown:
            raise ConfigError(f"Source(s) inconnue(s) : {', '.join(unknown)} (connues : {', '.join(KNOWN_SOURCES)})")
        if not self.sources:
            raise ConfigError("Aucune source active.")
        bad_formats = [f for f in self.output.formats if f not in KNOWN_FORMATS]
        if bad_formats:
            raise ConfigError(f"Format(s) d'export inconnu(s) : {', '.join(bad_formats)}")
        if self.interval_minutes < MIN_INTERVAL_MINUTES:
            raise ConfigError(f"L'intervalle doit être d'au moins {MIN_INTERVAL_MINUTES} minutes.")
        if self.location.radius_km < 0:
            raise ConfigError("Le rayon doit être positif.")
        if self.search.max_age_days is not None and self.search.max_age_days < 0:
            raise ConfigError("publiee_depuis_jours doit être positif.")
        if "rss" in self.sources and not self.rss_urls:
            raise ConfigError("La source « rss » est active mais aucune URL n'est configurée.")


def _str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"« {key} » doit être une liste de chaînes.")
    return [v.strip() for v in value if v.strip()]


def from_dict(data: dict[str, Any]) -> Config:
    """Construit une ``Config`` à partir du contenu (déjà parsé) du fichier TOML."""
    rech = data.get("recherche", {})
    loc = data.get("localisation", {})
    filt = data.get("filtres", {})
    out = data.get("sortie", {})
    src = data.get("sources", {})
    plan = data.get("planification", {})

    max_age = rech.get("publiee_depuis_jours", 7)
    out_dir = Path(out.get("dossier", "output"))
    cfg = Config(
        search=SearchConfig(
            keywords=_str_list(rech.get("mots_cles"), "recherche.mots_cles"),
            rome_codes=[c.upper() for c in _str_list(rech.get("codes_rome"), "recherche.codes_rome")],
            sectors=_str_list(rech.get("secteurs"), "recherche.secteurs"),
            contract_types=[c.upper() for c in _str_list(rech.get("types_contrat"), "recherche.types_contrat")],
            max_age_days=int(max_age) if max_age else None,
            max_results=int(rech.get("max_resultats", 150)),
        ),
        location=LocationConfig(
            city=str(loc.get("ville", "")).strip(),
            commune=str(loc.get("commune", "")).strip(),
            department=str(loc.get("departement", "")).strip(),
            radius_km=int(loc.get("rayon_km", 10)),
        ),
        filters=FilterConfig(
            exclusions=_str_list(filt.get("exclusions"), "filtres.exclusions"),
            exclude_required_license=bool(filt.get("exclure_permis_exige", False)),
        ),
        output=OutputConfig(
            directory=out_dir,
            formats=[f.lower() for f in _str_list(out.get("formats", ["csv"]), "sortie.formats")],
            seen_file=Path(out.get("fichier_vues", out_dir / "seen_jobs.json")),
            only_new=bool(out.get("seulement_nouvelles", True)),
            log_file=Path(out.get("fichier_log", "logs/job_bot.log")),
        ),
        sources=_str_list(src.get("actives", ["france_travail"]), "sources.actives"),
        rss_urls=_str_list(src.get("rss", {}).get("urls"), "sources.rss.urls"),
        fixture_path=Path(src["fixture"]["fichier"]) if src.get("fixture", {}).get("fichier") else None,
        interval_minutes=int(plan.get("intervalle_minutes", 60)),
    )
    return cfg


def load_config(path: Path | None) -> Config:
    """Charge le fichier TOML ; renvoie la configuration par défaut s'il n'existe pas."""
    if path is None or not path.exists():
        return Config()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} : TOML invalide ({exc})") from exc
    return from_dict(data)


def load_dotenv(path: Path = Path(".env")) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans écraser l'environnement existant."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
