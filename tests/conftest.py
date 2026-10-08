from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from job_bot.models import JobOffer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantit qu'aucun test n'ouvre de connexion réseau réelle."""
    def guard(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Accès réseau interdit pendant les tests")
    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def ft_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "francetravail_search.json").read_text(encoding="utf-8"))


def make_offer(**kwargs: Any) -> JobOffer:
    defaults: dict[str, Any] = {
        "source": "test",
        "id": "1",
        "title": "Vendeur",
        "published_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return JobOffer(**defaults)
