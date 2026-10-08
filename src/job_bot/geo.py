"""Localisation : résolution d'un nom de ville en code INSEE et calcul de distance.

La résolution utilise l'API publique et gratuite « Découpage administratif »
(https://geo.api.gouv.fr), sans clé.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

GEO_API_URL = "https://geo.api.gouv.fr/communes"


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    insee_code: str
    latitude: float | None = None
    longitude: float | None = None


def resolve_city(name: str, session: requests.Session | None = None) -> Place | None:
    """Renvoie la commune la plus peuplée portant ce nom, ou None."""
    http = session or requests
    try:
        resp = http.get(
            GEO_API_URL,
            params={"nom": name, "fields": "nom,code,centre,population", "boost": "population", "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Impossible de résoudre la ville %r : %s", name, exc)
        return None
    if not results:
        return None
    first = results[0]
    coords = (first.get("centre") or {}).get("coordinates") or [None, None]
    return Place(name=first.get("nom", name), insee_code=first["code"], longitude=coords[0], latitude=coords[1])


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance orthodromique en kilomètres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
