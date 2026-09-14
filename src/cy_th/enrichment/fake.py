# cy_th/enrichment/fake.py

"""Offline `DetailClient` for tests (no network)."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from cy_th.enrichment.errors import UsaSpendingDetailError


# === Client ===

@dataclass
class FakeDetailClient:
    """Scripted award-detail payloads keyed by generated USASpending id."""

    payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetch_calls: list[str] = field(default_factory=list)

    def fetch_award_detail(self, source_id: str) -> dict[str, Any]:
        self.fetch_calls.append(source_id)
        payload = self.payloads.get(source_id)
        if payload is None:
            raise UsaSpendingDetailError(f"fake detail missing for {source_id}")
        return dict(payload)
