from __future__ import annotations

import csv
import json
from pathlib import Path

from conftest import make_offer
from job_bot.storage import SeenStore, deduplicate, export


def test_deduplicate_by_uid() -> None:
    a = make_offer(id="1", title="Vendeur", company="A")
    b = make_offer(id="1", title="Vendeur (mis à jour)", company="A")
    assert deduplicate([a, b]) == [a]


def test_deduplicate_across_sources_by_fingerprint() -> None:
    a = make_offer(source="france_travail", id="1", title="Agent d'accueil", company="Mairie", location="Lyon")
    b = make_offer(source="rss", id="xyz", title="AGENT D'ACCUEIL ", company="mairie", location="lyon")
    c = make_offer(source="rss", id="abc", title="Agent d'accueil", company="Autre", location="Lyon")
    assert deduplicate([a, b, c]) == [a, c]


def test_deduplicate_keeps_offers_without_fingerprint_data() -> None:
    a = make_offer(id="1", title="")
    b = make_offer(id="2", title="")
    assert deduplicate([a, b]) == [a, b]


def test_seen_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "seen.json"
    store = SeenStore(path)
    first, second = make_offer(id="1"), make_offer(id="2")
    assert store.filter_new([first, second]) == [first, second]
    store.mark_seen([first])
    store.save()

    reloaded = SeenStore(path)
    assert len(reloaded) == 1
    assert first in reloaded
    assert reloaded.filter_new([first, second]) == [second]


def test_seen_store_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{pas du json", encoding="utf-8")
    assert len(SeenStore(path)) == 0


def test_export_csv_and_json(tmp_path: Path) -> None:
    offers = [make_offer(id="1", title="Vendeur", required_licenses=["B"]), make_offer(id="2", title="Caissier")]
    paths = export(offers, tmp_path, ["csv", "json"])
    assert sorted(p.suffix for p in paths) == [".csv", ".json"]

    csv_path = next(p for p in paths if p.suffix == ".csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert [r["title"] for r in rows] == ["Vendeur", "Caissier"]
    assert rows[0]["required_licenses"] == "B"

    json_path = next(p for p in paths if p.suffix == ".json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data[1]["id"] == "2"
    assert data[0]["published_at"].startswith("2026-10-01")
