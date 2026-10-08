"""Source générique : flux RSS 2.0 / Atom publics (sites carrières, job boards qui en proposent)."""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterator

import requests

from job_bot.models import JobOffer
from job_bot.sources.base import JobSource, SearchQuery, SourceError

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", text or ""))).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed(xml_text: str, source_name: str = "rss") -> list[JobOffer]:
    """Parse un flux RSS 2.0 ou Atom en liste de ``JobOffer``."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"Flux {source_name} illisible : {exc}") from exc

    offers: list[JobOffer] = []
    items = root.findall(".//item")
    if items:  # RSS 2.0
        for item in items:
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link).strip()
            offers.append(JobOffer(
                source=source_name,
                id=guid or hashlib.sha1(ET.tostring(item)).hexdigest()[:16],
                title=_clean(item.findtext("title")),
                url=link,
                description=_clean(item.findtext("description")),
                published_at=_parse_date(item.findtext("pubDate")),
            ))
        return offers
    for entry in root.findall(f"{ATOM}entry"):  # Atom
        link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        offers.append(JobOffer(
            source=source_name,
            id=(entry.findtext(f"{ATOM}id") or link).strip(),
            title=_clean(entry.findtext(f"{ATOM}title")),
            url=link,
            description=_clean(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")),
            published_at=_parse_date(entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")),
        ))
    return offers


class RssSource(JobSource):
    """Lit un ou plusieurs flux ; le filtrage se fait ensuite localement."""

    def __init__(self, name: str, urls: list[str], session: requests.Session | None = None) -> None:
        self.name = name
        self._urls = urls
        self._session = session or requests.Session()

    def search(self, query: SearchQuery) -> Iterator[JobOffer]:
        for url in self._urls:
            try:
                resp = self._session.get(url, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("Flux %s ignoré : %s", url, exc)
                continue
            yield from parse_feed(resp.text, self.name)
