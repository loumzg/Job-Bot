"""Interface commune des sources d'offres."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable

from job_bot.models import JobOffer


@dataclass(slots=True)
class SearchQuery:
    """Critères transmis aux sources (chaque source utilise ce qu'elle sait gérer).

    Les filtres sont de toute façon réappliqués localement par ``filters.py``.
    """

    keywords: list[str] = field(default_factory=list)
    rome_codes: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    commune: str = ""
    department: str = ""
    radius_km: int | None = None
    max_age_days: int | None = None
    contract_types: list[str] = field(default_factory=list)
    max_results: int = 150


class SourceError(RuntimeError):
    """Erreur levée par une source (réseau, authentification, format...)."""


class JobSource(ABC):
    """Une source d'offres : prend une requête, renvoie des ``JobOffer``."""

    name: str = "source"

    @abstractmethod
    def search(self, query: SearchQuery) -> Iterable[JobOffer]:
        """Renvoie les offres correspondant (au mieux) à la requête."""
