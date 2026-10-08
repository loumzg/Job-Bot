"""Modèle de données commun à toutes les sources."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def normalize_text(text: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces compactés (pour comparer des textes)."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", no_accents.lower()).strip()


@dataclass(slots=True)
class JobOffer:
    """Une offre d'emploi, quelle que soit sa source."""

    source: str
    id: str
    title: str
    url: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    published_at: datetime | None = None
    contract_type: str = ""
    rome_code: str = ""
    sector_code: str = ""
    sector_label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    required_licenses: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Identifiant unique stable : source + identifiant natif."""
        return f"{self.source}:{self.id}"

    @property
    def fingerprint(self) -> str:
        """Empreinte pour repérer la même offre publiée sur plusieurs sources."""
        parts = (self.title, self.company, self.location)
        return "|".join(normalize_text(p) for p in parts)

    def searchable_text(self) -> str:
        return normalize_text(" ".join([self.title, self.description, *self.required_licenses]))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat() if self.published_at else ""
        data["required_licenses"] = ", ".join(self.required_licenses)
        return data
