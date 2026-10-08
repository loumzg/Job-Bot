"""Sources d'offres pluggables.

Pour ajouter une source : créer une classe héritant de ``JobSource`` (méthode
``search``) puis la déclarer dans ``build_sources``.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from job_bot.config import Config
from job_bot.sources.base import JobSource, SearchQuery, SourceError
from job_bot.sources.fixture import FixtureSource
from job_bot.sources.france_travail import FranceTravailSource
from job_bot.sources.rss import RssSource

__all__ = [
    "JobSource", "SearchQuery", "SourceError",
    "FranceTravailSource", "RssSource", "FixtureSource",
    "build_sources", "demo_fixture_path", "SERVER_SIDE_KEYWORDS",
]

# Sources qui appliquent déjà les mots-clés côté serveur.
SERVER_SIDE_KEYWORDS = frozenset({FranceTravailSource.name})


def demo_fixture_path() -> Path:
    """Jeu d'offres fictives fourni avec le paquet (mode --dry-run)."""
    return Path(str(resources.files("job_bot") / "data" / "demo_offres.json"))


def build_sources(config: Config) -> list[JobSource]:
    sources: list[JobSource] = []
    for name in config.sources:
        if name == "france_travail":
            sources.append(FranceTravailSource(
                os.environ.get("FRANCE_TRAVAIL_CLIENT_ID", ""),
                os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET", ""),
            ))
        elif name == "rss":
            sources.append(RssSource("rss", config.rss_urls))
        elif name == "fixture":
            sources.append(FixtureSource(config.fixture_path or demo_fixture_path()))
    return sources
