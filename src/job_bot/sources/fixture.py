"""Source hors ligne : lit un fichier JSON au format de l'API France Travail.

Sert au mode « dry run » et aux démonstrations, sans identifiants ni réseau.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from job_bot.models import JobOffer
from job_bot.sources.base import JobSource, SearchQuery, SourceError
from job_bot.sources.france_travail import parse_search_response


class FixtureSource(JobSource):
    name = "fixture"

    def __init__(self, path: Path) -> None:
        self._path = path

    def search(self, query: SearchQuery) -> Iterator[JobOffer]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceError(f"Fichier d'exemple illisible ({self._path}) : {exc}") from exc
        for offer in parse_search_response(payload):
            offer.source = self.name
            yield offer
