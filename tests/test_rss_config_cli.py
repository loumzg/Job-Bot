from __future__ import annotations

from pathlib import Path

import pytest

from job_bot.cli import main
from job_bot.config import Config, ConfigError, from_dict, load_config
from job_bot.sources.base import SourceError
from job_bot.sources.rss import parse_feed

ROOT = Path(__file__).resolve().parents[1]

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Offres</title>
<item><title>Vendeur &amp; caissier</title><link>https://exemple.org/o/1</link>
<guid>o-1</guid><description>&lt;p&gt;CDI temps plein&lt;/p&gt;</description>
<pubDate>Mon, 05 Oct 2026 08:00:00 +0200</pubDate></item>
<item><title>Agent d'accueil</title><link>https://exemple.org/o/2</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Offres</title>
<entry><id>urn:offre:9</id><title>Magasinier</title><link href="https://exemple.org/o/9"/>
<updated>2026-10-04T12:00:00Z</updated><summary>Entrepôt</summary></entry></feed>"""


def test_parse_rss() -> None:
    offers = parse_feed(RSS, "rss")
    assert [o.id for o in offers] == ["o-1", "https://exemple.org/o/2"]
    assert offers[0].title == "Vendeur & caissier"
    assert offers[0].description == "CDI temps plein"
    assert offers[0].published_at is not None and offers[0].published_at.day == 5


def test_parse_atom() -> None:
    (offer,) = parse_feed(ATOM, "atom")
    assert (offer.id, offer.url, offer.description) == ("urn:offre:9", "https://exemple.org/o/9", "Entrepôt")


def test_parse_invalid_feed() -> None:
    with pytest.raises(SourceError):
        parse_feed("<rss>", "rss")


def test_example_config_is_valid() -> None:
    cfg = load_config(ROOT / "config.example.toml")
    cfg.validate()
    assert cfg.location.city == "Paris"
    assert cfg.search.keywords
    assert cfg.output.formats == ["csv", "json"]


def test_missing_config_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.toml") == Config()


@pytest.mark.parametrize("data", [
    {"sources": {"actives": ["indeed"]}},
    {"planification": {"intervalle_minutes": 1}},
    {"sortie": {"formats": ["xlsx"]}},
    {"sources": {"actives": ["rss"]}},
])
def test_invalid_config(data: dict) -> None:
    with pytest.raises(ConfigError):
        from_dict(data).validate()


def test_cli_dry_run(capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["--config", str(ROOT / "config.example.toml"), "--dry-run", "-k", "vendeur,accueil"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Vendeur en magasin de sport" in out
    assert "Agent d'accueil" in out
    assert "Livreur" not in out  # exclu : « permis B obligatoire »
    assert not any(tmp_path.iterdir())  # dry run : rien n'est écrit


def test_cli_fixture_writes_exports_and_remembers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    args = ["--config", "absent.toml", "-s", "fixture", "--depuis", "0", "-f", "json", "-k", "vendeur"]
    assert main(args) == 0
    assert len(list((tmp_path / "output").glob("offres_*.json"))) == 1
    assert (tmp_path / "output" / "seen_jobs.json").exists()
    assert (tmp_path / "logs" / "job_bot.log").exists()
    capsys.readouterr()

    assert main(args) == 0  # deuxième passage : tout est déjà vu
    assert "Aucune offre nouvelle" in capsys.readouterr().out


def test_run_forever_survives_failing_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    from job_bot import runner

    calls: list[int] = []
    sleeps: list[float] = []

    def cycle() -> None:
        calls.append(1)
        raise RuntimeError("panne passagère")

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever(Config(interval_minutes=30), cycle)
    assert len(calls) == 2
    assert 1790 < sleeps[0] <= 1800
