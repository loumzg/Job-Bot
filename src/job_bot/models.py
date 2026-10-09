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


# Variantes d'écriture ramenées à une forme unique (texte déjà normalisé).
_VARIANTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), repl)
    for pattern, repl in (
        (r"\bdeveloppeurs? (?:euse|se)s?\b", "developpeur"),
        (r"\bdeveloppeuses?\b", "developpeur"),
        (r"\bdevelopers?\b", "developpeur"),
        (r"\bdevs?\b", "developpeur"),
        (r"\bintegrat(?:eurs? (?:trice|rice)s?|rices?)\b", "integrateur"),
        (r"\bfull ?stack\b", "fullstack"),
        (r"\bfront ?end\b", "frontend"),
        (r"\bback ?end\b", "backend"),
        (r"\bweb ?(?:master|mestre)s?\b", "webmaster"),
        (r"\b(?:intelligence artificielle|artificial intelligence)\b", "ia"),
        (r"\bagentic\b", "agentique"),
        (r"\be commerce\b", "ecommerce"),
        (r"\b([a-z]+) js\b", r"\1js"),
    )
)


def canonical_text(text: str) -> str:
    """``normalize_text`` + variantes unifiées : « Développeuse full-stack » -> « developpeur fullstack »."""
    out = normalize_text(text)
    for pattern, repl in _VARIANTS:
        out = pattern.sub(repl, out)
    return out


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
        return canonical_text(" ".join([self.title, self.description, *self.required_licenses]))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat() if self.published_at else ""
        data["required_licenses"] = ", ".join(self.required_licenses)
        return data
