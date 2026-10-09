"""Résumé des offres dans le terminal : en-tête, tableau aligné, couleurs ANSI sobres.

Les couleurs sont désactivées si la sortie n'est pas un terminal, si ``NO_COLOR``
est défini ou si ``TERM=dumb`` (``FORCE_COLOR`` les force).
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from job_bot.models import JobOffer
from job_bot.report import city_of, contract_label, place_of, short_date

NO_OFFER = "Aucune offre nouvelle ne correspond aux critères."
CONTRACT_COLORS = {"CDI": "32", "CDD": "33", "MIS": "36", "SAI": "35"}
ACCENT = "38;5;99"  # violet de la palette du rapport (#5a3dd8 / #a898ff)


def _enable_windows_vt() -> bool:
    """Active les séquences ANSI dans la console Windows ; faux si impossible."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def use_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb" or not getattr(stream, "isatty", lambda: False)():
        return False
    return _enable_windows_vt()


def supports_unicode(stream: TextIO) -> bool:
    try:
        "─…·→".encode(getattr(stream, "encoding", None) or "ascii")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


@dataclass(slots=True)
class _Style:
    color: bool

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color and text else text


@dataclass(slots=True)
class _Column:
    key: str
    header: str
    width: int
    minimum: int
    align: str = "<"


def _fit(text: str, width: int, ellipsis: str) -> str:
    return text if len(text) <= width else text[: max(width - len(ellipsis), 0)].rstrip() + ellipsis


def _layout(columns: list[_Column], width: int) -> list[_Column]:
    """Rétrécit puis retire des colonnes (lieu, puis entreprise) pour tenir dans ``width``."""
    def total(cols: list[_Column]) -> int:
        return 2 + sum(c.width for c in cols) + 2 * (len(cols) - 1)

    cols = list(columns)
    ideal = {c.key: c.width for c in cols}
    for key in ("place", "company", "title"):
        col = next(c for c in cols if c.key == key)
        if total(cols) > width:
            col.width = max(col.minimum, col.width - (total(cols) - width))
    for key in ("place", "company"):
        if total(cols) <= width:
            break
        cols = [c for c in cols if c.key != key]
        for col in cols:
            if col.key in ("title", "company"):
                col.width = min(ideal[col.key], col.width + width - total(cols))
    return cols


def render_summary(
    offers: Sequence[JobOffer],
    *,
    fetched: int | None = None,
    keywords: Sequence[str] = (),
    exported: Sequence[Path] = (),
    color: bool = False,
    width: int = 100,
    unicode: bool = True,
) -> str:
    """Texte prêt à afficher : en-tête, tableau des offres, liens et fichiers exportés."""
    if not offers:
        return NO_OFFER
    st = _Style(color)
    rule, ellipsis, dot, arrow = ("─", "…", "·", "→") if unicode else ("-", "...", "-", "->")
    width = max(width, 60)

    rows: list[dict[str, Any]] = []
    for n, o in enumerate(offers, 1):
        rows.append({
            "n": str(n),
            "date": short_date(o.published_at.date()) if o.published_at else "?",
            "contract": contract_label(o.contract_type) if o.contract_type else "?",
            "code": o.contract_type.upper(),
            "title": o.title or "(sans intitulé)",
            "company": o.company,
            "place": place_of(o.location) or city_of(o.location),
        })

    def natural(key: str, header: str) -> int:
        return max(len(header), *(len(r[key]) for r in rows))

    columns = _layout([
        _Column("n", "#", natural("n", "#"), 1, ">"),
        _Column("date", "Date", natural("date", "Date"), 4),
        _Column("contract", "Contrat", natural("contract", "Contrat"), 7),
        _Column("title", "Intitulé", min(natural("title", "Intitulé"), 52), 30),
        _Column("company", "Entreprise", min(natural("company", "Entreprise"), 24), 12),
        _Column("place", "Lieu", min(natural("place", "Lieu"), 20), 10),
    ], width)

    def cell(col: _Column, text: str) -> str:
        return f"{_fit(text, col.width, ellipsis):{col.align}{col.width}}"

    count = len(offers)
    plural = "s" if count > 1 else ""
    headline = f"{count} offre{plural} retenue{plural}"
    if fetched and fetched != count:
        headline += f" sur {fetched} récupérée{'s' if fetched > 1 else ''}"
    lines = ["", f"  {st('Job-Bot', '1;' + ACCENT)}  {st(dot, '2')}  {st(headline, '1')}"]
    if keywords:
        lines.append("  " + st("mots-clés : " + ", ".join(keywords), "2"))
    lines.append("")
    lines.append(("  " + "  ".join(st(cell(c, c.header), "2") for c in columns)).rstrip())
    lines.append("  " + "  ".join(st(rule * c.width, "2") for c in columns))
    for row in rows:
        parts = []
        for col in columns:
            text = cell(col, row[col.key])
            if col.key == "n" or col.key == "date":
                text = st(text, "2")
            elif col.key == "contract":
                text = st(text, CONTRACT_COLORS.get(row["code"], "0"))
            elif col.key == "title":
                text = st(text, "1")
            parts.append(text)
        lines.append(("  " + "  ".join(parts)).rstrip())

    links = [(n, o.url) for n, o in enumerate(offers, 1) if o.url]
    if links:
        lines += ["", "  " + st("Liens", "1")]
        pad = len(str(links[-1][0]))
        lines += [f"  {st(f'{n:>{pad}}', '2')}  {url}" for n, url in links]

    mix = Counter(contract_label(o.contract_type) for o in offers).most_common()
    lines += ["", "  " + f" {st(dot, '2')} ".join(f"{label} {st(str(n), '1')}" for label, n in mix)]
    for path in exported:
        lines.append(f"  {st(arrow, ACCENT)} {path}")
    lines.append("")
    return "\n".join(lines)
