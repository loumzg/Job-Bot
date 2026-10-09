from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from html import unescape
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import make_offer
from job_bot.cli import main
from job_bot.console import NO_OFFER, render_summary, use_color
from job_bot.report import ReportContext, city_of, highlight, render_html, safe_json, top_terms
from job_bot.storage import export

ROOT = Path(__file__).resolve().parents[1]
WHEN = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

EVIL = make_offer(
    id="x1",
    title="<script>alert('titre')</script> Vendeur",
    company='"><img src=x onerror=alert(1)>',
    location="69 - LYON 03 <b>",
    description="</script><script>alert('desc')</script> & conseil",
    url="javascript:alert(1)",
    contract_type='CDI"><svg onload=alert(2)>',
)


def offers() -> list:
    return [
        make_offer(id="1", title="Vendeur en magasin", company="Sport Exemple", location="69 - LYON 07",
                   contract_type="CDI", description="Conseil client et encaissement.",
                   url="https://exemple.org/o/1"),
        make_offer(id="2", title="Agent d'accueil", company="Services Exemple", location="69 - VILLEURBANNE",
                   contract_type="CDD", description="Accueil physique et conseil client.",
                   published_at=datetime(2026, 9, 28, tzinfo=timezone.utc)),
        make_offer(source="rss", id="3", title="Vendeur saisonnier", location="Lyon", contract_type="SAI"),
    ]


def data_block(page: str) -> list[dict]:
    match = re.search(r'<script type="application/json" id="job-data">(.*?)</script>', page, re.S)
    assert match
    return json.loads(match.group(1))


def test_report_structure() -> None:
    page = render_html(offers(), ReportContext(keywords=["vendeur"], place="Lyon", radius_km=10,
                                               fetched=5, generated_at=WHEN))
    assert page.startswith("<!doctype html>")
    assert '<html lang="fr">' in page
    assert 'class="bento"' in page
    assert page.count('<article class="card"') == 3
    assert page.count('class="chip"') == 3
    assert "3 retenues sur 5 récupérées" in page
    assert "<mark>Vendeur</mark> en magasin" in page
    assert '<option value="score">Pertinence</option>' in page
    assert 'href="https://exemple.org/o/1"' in page
    assert 'rel="noopener noreferrer"' in page
    assert "prefers-reduced-motion" in page
    assert "fonts.googleapis.com" in page
    assert "Bricolage+Grotesque" in page and "JetBrains+Mono" in page
    assert "Plex" not in page
    assert ('<p class="credit">Créé par <a href="https://github.com/loumzg" target="_blank" '
            'rel="noopener">loun3s</a></p>') in page
    assert not re.search(r'<(?:script|link)[^>]+src="https?://(?!fonts\.)', page)
    data = data_block(page)
    assert [d["c"] for d in data] == ["CDI", "CDD", "SAI"]
    assert data[0]["k"] == 1 and data[1]["k"] == 0
    assert data[1]["v"] == "Villeurbanne"


def test_report_csp_allows_only_its_own_scripts() -> None:
    page = render_html(offers(), ReportContext(generated_at=WHEN))
    csp = unescape(re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1))
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 2
    for body in scripts:
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp
    assert "default-src 'none'" in csp and "unsafe-eval" not in csp


def test_report_escapes_everything() -> None:
    page = render_html([EVIL], ReportContext(keywords=["<b>vendeur</b>"], place="<i>Lyon</i>", generated_at=WHEN))
    assert "<script>alert" not in page
    for raw in ("<img", "<svg onload", "<b>vendeur", "<i>Lyon", "LYON 03 <b>"):
        assert raw not in page
    assert "&lt;script&gt;alert(&#x27;titre&#x27;)&lt;/script&gt;" in page
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in page
    assert "javascript:" not in page
    assert "Voir l'offre" not in page
    raw = re.search(r'id="job-data">(.*?)</script>', page, re.S).group(1)
    assert "<" not in raw and ">" not in raw and "&" not in raw
    assert data_block(page)[0]["t"].startswith("script alert titre")


def test_safe_json_neutralises_html() -> None:
    text = safe_json({"a": "</script><!-- &  "})
    assert "</" not in text and "<!--" not in text and "&" not in text
    assert json.loads(text) == {"a": "</script><!-- &  "}


def test_highlight_and_helpers() -> None:
    assert highlight("Agent d'accueil <b>", ["accueil"]) == "Agent d&#x27;<mark>accueil</mark> &lt;b&gt;"
    assert highlight("Préparateur", ["preparateur"]) == "<mark>Préparateur</mark>"
    assert city_of("69 - LYON 07") == "Lyon"
    assert city_of("69 - CALUIRE-ET-CUIRE") == "Caluire-et-Cuire"
    assert city_of("Bordeaux (33)") == "Bordeaux (33)"
    assert dict(top_terms(offers())) == {"client": 2, "conseil": 2, "vendeur": 2}


def test_empty_report() -> None:
    page = render_html([], ReportContext(generated_at=WHEN))
    assert "Aucune offre ne correspond" in page
    assert 'class="bento"' not in page
    assert data_block(page) == []


def test_export_html_format(tmp_path: Path) -> None:
    (path,) = export(offers(), tmp_path, ["html"], when=WHEN, context=ReportContext(keywords=["vendeur"]))
    assert path.name == "offres_20261008-090000.html"
    assert "saisonnier</h3>" in path.read_text(encoding="utf-8")


def test_cli_dry_run_writes_only_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "demo" / "rapport.html"
    assert main(["--config", "absent.toml", "--dry-run", "-k", "intégrateur web", "--rapport", str(target)]) == 0
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["rapport.html"]
    page = target.read_text(encoding="utf-8")
    assert "<mark>Intégrateur</mark> <mark>web</mark> HTML / CSS (H/F)</h3>" in page and "Démo hors ligne" in page
    assert str(target) in capsys.readouterr().out


def test_cli_accepts_html_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["--config", "absent.toml", "-s", "fixture", "--depuis", "0", "-f", "html", "-k", "webmaster"]) == 0
    assert len(list((tmp_path / "output").glob("offres_*.html"))) == 1


def test_console_summary_is_aligned_and_plain_without_color() -> None:
    text = render_summary(offers(), fetched=4, keywords=["vendeur"], width=80, unicode=False)
    assert "\033[" not in text
    assert "3 offres retenues sur 4" in text
    lines = text.splitlines()
    assert all(len(line) <= 80 for line in lines)
    header = next(line for line in lines if "Intitul" in line)
    rows = [line for line in lines if "Vendeur" in line or "Agent" in line]
    start = header.index("Intitul")
    assert all(row[start:].startswith(("Vendeur", "Agent")) for row in rows)
    assert render_summary([]) == NO_OFFER


def test_console_color_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(Tty()) is False
    monkeypatch.delenv("NO_COLOR")
    assert use_color(io.StringIO()) is False
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert use_color(io.StringIO()) is True
    assert "\033[1m" in render_summary(offers(), color=True)


def test_report_deck_shortens_long_keyword_lists() -> None:
    keywords = ["développeur web", "webmaster", "intégrateur web", "développeur php", "développeur ia", "react"]
    page = render_html(offers(), ReportContext(keywords=keywords, generated_at=WHEN))
    assert "développeur php" in page and " et 2 autres" in page
    assert "« react »" not in page.replace("\xa0", " ")
