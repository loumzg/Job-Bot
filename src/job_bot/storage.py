"""Déduplication, mémorisation des offres déjà vues et exports CSV / JSON."""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from job_bot.models import JobOffer

log = logging.getLogger(__name__)

EXPORT_FIELDS = [f.name for f in fields(JobOffer)]


def deduplicate(offers: Iterable[JobOffer]) -> list[JobOffer]:
    """Supprime les doublons : même identifiant de source, ou même intitulé/entreprise/lieu."""
    seen_uids: set[str] = set()
    seen_prints: set[str] = set()
    unique: list[JobOffer] = []
    for offer in offers:
        fp = offer.fingerprint
        if offer.uid in seen_uids or (fp.strip("|") and fp in seen_prints):
            continue
        seen_uids.add(offer.uid)
        seen_prints.add(fp)
        unique.append(offer)
    return unique


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class SeenStore:
    """Offres déjà vues, persistées en JSON : ``{uid: date de première vue}``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, str] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._seen = {str(k): str(v) for k, v in data.items()}
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Fichier des offres vues illisible (%s), on repart de zéro : %s", path, exc)

    def __contains__(self, offer: JobOffer) -> bool:
        return offer.uid in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def filter_new(self, offers: Iterable[JobOffer]) -> list[JobOffer]:
        return [o for o in offers if o not in self]

    def mark_seen(self, offers: Iterable[JobOffer], when: datetime | None = None) -> None:
        stamp = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        for offer in offers:
            self._seen.setdefault(offer.uid, stamp)

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self._seen, ensure_ascii=False, indent=1, sort_keys=True))


def export_csv(offers: list[JobOffer], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM : ouverture correcte dans Excel
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(o.to_dict() for o in offers)
    return path


def export_json(offers: list[JobOffer], path: Path) -> Path:
    _atomic_write(path, json.dumps([o.to_dict() for o in offers], ensure_ascii=False, indent=2))
    return path


def export(offers: list[JobOffer], directory: Path, formats: Iterable[str], when: datetime | None = None) -> list[Path]:
    """Écrit un fichier par format, horodaté : ``offres_AAAAMMJJ-HHMMSS.<ext>``."""
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    written: list[Path] = []
    for fmt in formats:
        target = directory / f"offres_{stamp}.{fmt}"
        written.append(export_csv(offers, target) if fmt == "csv" else export_json(offers, target))
    return written
