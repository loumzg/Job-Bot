"""Rapport HTML autonome : chiffres clés en grille « bento » et cartes d'offres filtrables.

Tout le texte issu des offres passe par ``html.escape`` ; les données utilisées par le
script côté client sont injectées en JSON neutralisé (``<``, ``>``, ``&`` encodés).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import escape
from importlib import resources
from typing import Iterable
from urllib.parse import urlsplit

from job_bot import __version__
from job_bot.filters import matches_keywords
from job_bot.geo import haversine_km
from job_bot.models import JobOffer, canonical_text, normalize_text

CONTRACT_LABELS = {
    "CDI": "CDI", "CDD": "CDD", "MIS": "Intérim", "SAI": "Saisonnier",
    "LIB": "Libéral", "FRA": "Franchise", "CCE": "Commerce", "DIN": "CDI intérimaire",
}
CONTRACT_ORDER = ["CDI", "CDD", "MIS", "SAI"]
SOURCE_LABELS = {"france_travail": "France Travail", "rss": "Flux RSS", "fixture": "Démo hors ligne"}
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTHS_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
               "septembre", "octobre", "novembre", "décembre"]
STOPWORDS = frozenset(
    "avec dans pour sans sous chez entre leur leurs vous votre nous notre cette ces tous tout toute "
    "toutes plus moins pendant apres avant fin debut etre sont aussi ainsi sera bien tres "
    "poste postes h f".split()
)
TIMELINE_MAX_DAYS = 28
KEYWORDS_SHOWN = 4
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..700"
             "&family=JetBrains+Mono:wght@400;500&display=swap")
AUTHOR_NAME = "loun3s"
AUTHOR_URL = "https://github.com/loumzg"
_DEPT_PREFIX = re.compile(r"^\s*\d[\dAB]?\d?\s*-\s*")
_ARRONDISSEMENT = re.compile(r"\s+\d{1,2}(?:e|er|eme)?$", re.IGNORECASE)
_WORD = re.compile(r"\w+")
_LOWER_WORDS = frozenset({"et", "sur", "sous", "en", "le", "la", "les", "de", "du", "des", "au", "aux", "d", "l"})


@dataclass(slots=True)
class ReportContext:
    """Contexte de la recherche affiché dans le rapport."""

    keywords: list[str] = field(default_factory=list)
    place: str = ""
    radius_km: int | None = None
    center: tuple[float, float] | None = None
    fetched: int | None = None
    generated_at: datetime | None = None


def _asset(name: str) -> str:
    return (resources.files("job_bot") / "templates" / name).read_text(encoding="utf-8")


def safe_json(data: object) -> str:
    """JSON insérable tel quel dans un élément ``<script>``."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for char, code in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                       (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(char, code)
    return text


def safe_url(url: str) -> str:
    """URL d'offre uniquement si elle est en http(s), sinon chaîne vide."""
    try:
        return url if urlsplit(url.strip()).scheme.lower() in ("http", "https") else ""
    except ValueError:
        return ""


def city_of(location: str) -> str:
    """« 69 - LYON 07 » -> « Lyon » ; les libellés libres (RSS) sont gardés tels quels."""
    name = _DEPT_PREFIX.sub("", location or "").strip()
    name = _ARRONDISSEMENT.sub("", name).strip()
    if name.isupper():
        words = re.split(r"([\s'-]+)", name.lower())
        name = "".join(
            w if i and w in _LOWER_WORDS else w[:1].upper() + w[1:] for i, w in enumerate(words)
        )
    return name


def place_of(location: str) -> str:
    """Libellé complet sans le département : « 69 - LYON 07 » -> « Lyon 07 »."""
    raw = _DEPT_PREFIX.sub("", location or "").strip()
    suffix = raw[len(_ARRONDISSEMENT.sub("", raw)):]
    return (city_of(location) + suffix).strip()


def contract_label(code: str) -> str:
    return CONTRACT_LABELS.get(code.upper(), code) if code else "Non précisé"


def source_label(name: str) -> str:
    return SOURCE_LABELS.get(name, name)


def short_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]}"


def long_date(value: date) -> str:
    return f"{value.day} {MONTHS_LONG[value.month - 1]} {value.year}"


def matched_keywords(offer: JobOffer, keywords: Iterable[str]) -> list[str]:
    return [k for k in keywords if k.strip() and matches_keywords(offer, [k])]


def highlight(text: str, words: Iterable[str]) -> str:
    """Échappe ``text`` et entoure de ``<mark>`` les mots qui contiennent un des ``words``."""
    wanted = [w for w in words if w]
    if not wanted:
        return escape(text)
    out: list[str] = []
    last = 0
    for match in _WORD.finditer(text):
        token = match.group()
        forms = (normalize_text(token), canonical_text(token))
        # mots courts (« ia », « php ») : mot entier seulement, pour ne pas surligner « spécialisé »
        if any(w == f if len(w) <= 3 else w in f for w in wanted for f in forms):
            out.append(escape(text[last:match.start()]))
            out.append(f"<mark>{escape(token)}</mark>")
            last = match.end()
    out.append(escape(text[last:]))
    return "".join(out)


def top_terms(offers: Iterable[JobOffer], limit: int = 8) -> list[tuple[str, int]]:
    """Mots les plus fréquents (nombre d'offres qui les contiennent), sous leur forme accentuée."""
    counts: Counter[str] = Counter()
    forms: dict[str, Counter[str]] = {}
    for offer in offers:
        seen: set[str] = set()
        for token in _WORD.findall(f"{offer.title} {offer.description}"):
            key = normalize_text(token)
            if len(key) < 4 or key in STOPWORDS or key.isdigit():
                continue
            forms.setdefault(key, Counter())[token.lower()] += 1
            seen.add(key)
        counts.update(seen)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(forms[k].most_common(1)[0][0], n) for k, n in ranked[:limit] if n > 1]


def _distance(offer: JobOffer, center: tuple[float, float] | None) -> float | None:
    if center is None or offer.latitude is None or offer.longitude is None:
        return None
    return haversine_km(center[0], center[1], offer.latitude, offer.longitude)


def _pct(part: int, total: int) -> str:
    return f"{round(100 * part / total)} %" if total else "0 %"


def _contract_slot(code: str) -> int:
    code = code.upper()
    return CONTRACT_ORDER.index(code) + 1 if code in CONTRACT_ORDER else 5


def _bars(items: list[tuple[str, int]], total: int) -> str:
    peak = max((n for _, n in items), default=1)
    rows = []
    for i, (label, n) in enumerate(items):
        rows.append(
            f'<li style="--i:{i}"><span class="bar-label">{escape(label)}</span>'
            f'<span class="bar-value">{n}</span>'
            f'<span class="bar-track" title="{escape(label)} : {n} offre(s), {_pct(n, total)}">'
            f'<span class="bar-fill" style="--w:{100 * n / peak:.1f}%"></span></span></li>'
        )
    return f'<ol class="bars">{"".join(rows)}</ol>'


def _donut(parts: list[tuple[str, str, int]], total: int) -> str:
    """Anneau SVG : ``parts`` = (code, libellé, effectif)."""
    gap = 1.2 if len(parts) > 1 else 0.0
    offset = 25.0
    arcs = []
    for code, label, n in parts:
        length = 100 * n / total
        arcs.append(
            f'<circle class="arc" data-slot="{_contract_slot(code)}" r="15.9155" cx="21" cy="21" '
            f'stroke-dasharray="{max(length - gap, 0.4):.2f} {100 - max(length - gap, 0.4):.2f}" '
            f'stroke-dashoffset="{offset:.2f}"><title>{escape(label)} : {n} ({_pct(n, total)})</title></circle>'
        )
        offset -= length
    lead_code, lead_label, lead_n = parts[0]
    legend = "".join(
        f'<li><i class="dot" data-slot="{_contract_slot(c)}"></i><span>{escape(lbl)}</span>'
        f'<b>{n}</b><small>{_pct(n, total)}</small></li>'
        for c, lbl, n in parts
    )
    return (
        '<div class="donut-wrap"><svg class="donut" viewBox="0 0 42 42" role="img" '
        f'aria-label="Répartition par type de contrat">'
        f'<circle class="donut-hole" r="15.9155" cx="21" cy="21"></circle>{"".join(arcs)}'
        f'<text x="21" y="21" class="donut-num">{_pct(lead_n, total).replace(" ", "")}</text>'
        f'<text x="21" y="26.5" class="donut-cap">{escape(lead_label)}</text></svg>'
        f'<ul class="legend">{legend}</ul></div>'
    )


def _timeline(days: list[date]) -> str:
    """Barres verticales SVG : nombre d'offres publiées par jour."""
    if not days:
        return ""
    last = max(days)
    first = max(min(days), last - timedelta(days=TIMELINE_MAX_DAYS - 1))
    span = (last - first).days + 1
    counts = Counter(d for d in days if d >= first)
    peak = max(counts.values())
    step, width, height = 10, 6, 44
    bars = []
    for i in range(span):
        day = first + timedelta(days=i)
        n = counts.get(day, 0)
        h = max(height * n / peak, 1.5)
        cls = "tl-bar" if n else "tl-bar tl-empty"
        bars.append(
            f'<rect class="{cls}" style="--i:{i}" x="{i * step + 2}" y="{height - h + 2:.1f}" width="{width}" '
            f'height="{h:.1f}" rx="2"><title>{short_date(day)} : {n} offre(s)</title></rect>'
        )
    return (
        f'<svg class="timeline" viewBox="0 0 {span * step + 2} {height + 4}" role="img" '
        f'aria-label="Offres publiées par jour">{"".join(bars)}</svg>'
        f'<div class="tl-axis"><span>{short_date(first)}</span><span>{short_date(last)}</span></div>'
    )


def _sources(counter: Counter[str], total: int) -> str:
    parts = counter.most_common()
    segs = "".join(
        f'<span class="seg" data-slot="{i % 5 + 1}" style="--w:{100 * n / total:.2f}%" '
        f'title="{escape(source_label(name))} : {n}"></span>'
        for i, (name, n) in enumerate(parts)
    )
    legend = "".join(
        f'<li><i class="dot" data-slot="{i % 5 + 1}"></i><span>{escape(source_label(name))}</span><b>{n}</b></li>'
        for i, (name, n) in enumerate(parts)
    )
    return f'<div class="stack">{segs}</div><ul class="legend legend-inline">{legend}</ul>'


def _card(index: int, offer: JobOffer, keywords: list[str], km: float | None) -> str:
    matched = matched_keywords(offer, keywords)
    words = [w for k in matched for w in {*normalize_text(k).split(), *canonical_text(k).split()}]
    published = offer.published_at.date() if offer.published_at else None
    url = safe_url(offer.url)
    meta = [m for m in (offer.company, place_of(offer.location)) if m]
    if km is not None:
        meta.append(f"à {km:.0f} km" if km >= 1 else "à moins d'1 km")
    desc = offer.description.strip()
    if len(desc) > 260:
        desc = desc[:257].rsplit(" ", 1)[0] + "…"
    parts = [
        f'<article class="card" data-i="{index}" style="--i:{min(index, 12)}">',
        '<div class="card-top">',
        f'<span class="tag"><i class="dot" data-slot="{_contract_slot(offer.contract_type)}"></i>'
        f'{escape(contract_label(offer.contract_type))}</span>',
        f'<time datetime="{published.isoformat()}">{short_date(published)} {published.year}</time>' if published else "",
        "</div>",
        f'<h3 class="card-title">{highlight(offer.title or "Offre sans intitulé", words)}</h3>',
        f'<p class="card-meta">{"".join(f"<span>{escape(m)}</span>" for m in meta)}</p>' if meta else "",
        f'<p class="card-desc">{highlight(desc, words)}</p>' if desc else "",
    ]
    if matched:
        chips = "".join(f"<li>{escape(k)}</li>" for k in matched)
        parts.append(f'<ul class="card-kw" aria-label="Mots-clés correspondants">{chips}</ul>')
    parts.append(f'<div class="card-foot"><span class="src">{escape(source_label(offer.source))}</span>')
    if url:
        parts.append(
            f'<a class="card-link" href="{escape(url)}" target="_blank" rel="noopener noreferrer">'
            'Voir l\'offre<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5"/></svg></a>'
        )
    parts.append("</div></article>")
    return "".join(parts)


def _csp(scripts: Iterable[str]) -> str:
    hashes = " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(s.encode('utf-8')).digest()).decode()}'" for s in scripts
    )
    return (
        "default-src 'none'; "
        f"script-src {hashes}; "
        "style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src data:; "
        "base-uri 'none'; form-action 'none'"
    )


def render_html(offers: list[JobOffer], context: ReportContext | None = None) -> str:
    """Construit le rapport complet (un seul fichier, sans dépendance hors Google Fonts)."""
    ctx = context or ReportContext()
    generated = ctx.generated_at or datetime.now(timezone.utc)
    total = len(offers)
    keywords = [k for k in ctx.keywords if k.strip()]
    distances = [_distance(o, ctx.center) for o in offers]

    contracts = Counter((o.contract_type or "").upper() for o in offers)
    contract_parts = sorted(
        ((c, contract_label(c), n) for c, n in contracts.items()),
        key=lambda p: (-p[2], _contract_slot(p[0])),
    )
    cities = Counter(city_of(o.location) or "Non précisé" for o in offers)
    city_items = cities.most_common(5)
    if len(cities) > 5:
        city_items.append(("Autres", total - sum(n for _, n in city_items)))
    sources = Counter(o.source for o in offers)
    terms = top_terms(offers)
    days = [o.published_at.date() for o in offers if o.published_at]

    title = f"{total} offre{'s' if total > 1 else ''}"
    period = (f"publiées du {short_date(min(days))} au {short_date(max(days))}"
              if days and min(days) != max(days) else (f"publiées le {short_date(days[0])}" if days else ""))
    criteria = []
    if keywords:
        shown = ", ".join(f"« {escape(k)} »" for k in keywords[:KEYWORDS_SHOWN])
        more = len(keywords) - KEYWORDS_SHOWN
        criteria.append(f"Recherche {shown}" + (f" et {more} autre{'s' if more > 1 else ''}" if more > 0 else ""))
    if ctx.place:
        where = escape(ctx.place)
        criteria.append(f"autour de {where} ({ctx.radius_km} km)" if ctx.radius_km else where)
    if period:
        criteria.append(period)
    deck = " · ".join(criteria) or "Toutes les offres retenues par vos filtres."
    fetched = (f'<p class="hero-sub">{total} retenue{"s" if total > 1 else ""} sur '
               f'{ctx.fetched} récupérée{"s" if ctx.fetched > 1 else ""}</p>'
               if ctx.fetched and ctx.fetched != total else "")

    if total:
        bento = (
            '<section class="bento" aria-label="Chiffres clés">'
            f'<article class="tile tile-hero" style="--i:0"><h2 class="tile-k">Offres retenues</h2>'
            f'<p class="hero-num">{total}</p>{fetched}'
            f'<div class="tile-block"><h3 class="tile-k">Rythme de publication</h3>{_timeline(days)}</div>'
            f'<div class="tile-block"><h3 class="tile-k">Par source</h3>{_sources(sources, total)}</div></article>'
            f'<article class="tile" style="--i:1"><h2 class="tile-k">Type de contrat</h2>'
            f'{_donut(contract_parts, total)}</article>'
            f'<article class="tile" style="--i:2"><h2 class="tile-k">Par ville</h2>{_bars(city_items, total)}</article>'
            f'<article class="tile" style="--i:3"><h2 class="tile-k">Mots les plus fréquents</h2>'
            f'{_bars(terms, total) if terms else "<p class=tile-empty>Pas assez d’offres.</p>"}</article>'
            '</section>'
        )
    else:
        bento = '<p class="empty-report">Aucune offre ne correspond aux critères pour le moment.</p>'

    contract_codes = [c for c, _, _ in contract_parts]
    chips = "".join(
        f'<button type="button" class="chip" data-contract="{escape(c)}" aria-pressed="false">'
        f'<i class="dot" data-slot="{_contract_slot(c)}"></i>{escape(contract_label(c))}<b>{contracts[c]}</b></button>'
        for c in contract_codes
    )
    city_opts = "".join(f'<option value="{escape(c)}">{escape(c)} ({n})</option>' for c, n in cities.most_common())
    source_opts = "".join(
        f'<option value="{escape(s)}">{escape(source_label(s))} ({n})</option>' for s, n in sources.most_common()
    )
    sort_opts = ['<option value="recent">Plus récentes</option>', '<option value="old">Plus anciennes</option>']
    if keywords:
        sort_opts.insert(0, '<option value="score">Pertinence</option>')
    if any(d is not None for d in distances):
        sort_opts.append('<option value="distance">Plus proches</option>')
    sort_opts.append('<option value="company">Entreprise A → Z</option>')

    data = [
        {
            "c": (o.contract_type or "").upper(),
            "v": city_of(o.location) or "Non précisé",
            "s": o.source,
            "d": o.published_at.timestamp() if o.published_at else 0,
            "k": len(matched_keywords(o, keywords)),
            "km": round(km, 1) if km is not None else None,
            "co": normalize_text(o.company),
            "t": normalize_text(" ".join([o.title, o.company, o.location, o.description, contract_label(o.contract_type)])),
        }
        for o, km in zip(offers, distances)
    ]
    cards = "".join(_card(i, o, keywords, km) for i, (o, km) in enumerate(zip(offers, distances)))

    theme_js = _asset("theme.js")
    app_js = _asset("report.js")
    stamp = generated.astimezone()
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(_csp([theme_js, app_js]))}">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="Job-Bot {escape(__version__)}">
<title>Job-Bot · {title} · {escape(short_date(stamp.date()))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_URL}">
<script>{theme_js}</script>
<style>{_asset("report.css")}</style>
</head>
<body>
<div class="page">
<header class="masthead">
<a class="brand" href="#top" id="top">Job<em>-</em>Bot</a>
<p class="edition">Rapport du {escape(long_date(stamp.date()))}, {stamp:%H:%M}</p>
<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Basculer le thème clair / sombre">
<svg viewBox="0 0 24 24" aria-hidden="true"><circle class="sun" cx="12" cy="12" r="4.2"/><path class="rays" d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/><path class="moon" d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/></svg>
</button>
</header>
<section class="hero">
<p class="kicker">Recherche d'emploi · sélection du jour</p>
<h1>{title} <em>à lire de près.</em></h1>
<p class="deck">{deck}</p>
</section>
{bento}
<section class="offers" aria-labelledby="offers-title">
<div class="section-head"><h2 id="offers-title">Les offres</h2><p class="count" id="count" aria-live="polite">{total} sur {total}</p></div>
<div class="toolbar" role="search">
<label class="search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
<input type="search" id="q" placeholder="Intitulé, entreprise, ville…" autocomplete="off" aria-label="Rechercher dans les offres"></label>
<div class="chips" role="group" aria-label="Type de contrat">{chips}</div>
<div class="selects">
<label><span>Ville</span><select id="city"><option value="">Toutes</option>{city_opts}</select></label>
<label{' hidden' if len(sources) < 2 else ''}><span>Source</span><select id="source"><option value="">Toutes</option>{source_opts}</select></label>
<label><span>Tri</span><select id="sort">{"".join(sort_opts)}</select></label>
<button type="button" class="reset" id="reset" hidden>Effacer</button>
</div>
</div>
<div class="grid" id="grid">{cards}</div>
<p class="empty" id="empty" hidden>Aucune offre ne correspond à ces filtres.</p>
</section>
<footer class="colophon">
<p>Généré par Job-Bot {escape(__version__)}. Vérifiez chaque annonce sur son site d'origine avant de postuler.</p>
<p class="credit">Créé par <a href="{AUTHOR_URL}" target="_blank" rel="noopener">{AUTHOR_NAME}</a></p>
</footer>
</div>
<script type="application/json" id="job-data">{safe_json(data)}</script>
<script>{app_js}</script>
</body>
</html>
"""
