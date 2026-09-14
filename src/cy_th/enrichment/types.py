# cy_th/enrichment/types.py

"""Typed models for enrichment cache records and overlay results."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from cy_th.schema.enums import HydrationStatus, SnapshotSource, SnapshotStatus


# === Resource ===

class EnrichmentResource(StrEnum):
    """Cached USASpending resource kind."""

    AWARD = "award"
    IDV = "idv"


# === Local Snapshots ===

@dataclass(frozen=True, slots=True)
class LocalAwardRow:
    """Minimal Award fields read from the pinned Parquet set."""

    award_id: str
    snapshot_status: SnapshotStatus
    snapshot_source: SnapshotSource
    observed_total_obligation: Decimal | None
    observed_current_value: Decimal | None
    observed_potential_value: Decimal | None
    date_signed: date | None
    parent_idv_id: str | None

@dataclass(frozen=True, slots=True)
class LocalIdvRow:
    """Minimal IDV stub fields from the pinned Parquet set."""

    idv_id: str
    piid: str
    award_key_agency_id: str
    type_code: str | None
    type_label: str | None
    hydration_status: HydrationStatus


# === Overlay Results ===

@dataclass(frozen=True, slots=True)
class AwardEnrichment:
    """Overlay result for one Award (does not mutate Parquet)."""

    award_id: str
    cache_path: Path
    cache_hit: bool
    endpoint: str
    retrieved_at: str
    date_signed: date | None
    money_applied: bool
    observed_total_obligation: Decimal | None
    observed_current_value: Decimal | None
    observed_potential_value: Decimal | None
    snapshot_status: SnapshotStatus
    snapshot_source: SnapshotSource
    local: LocalAwardRow

@dataclass(frozen=True, slots=True)
class IdvEnrichment:
    """Overlay result for one IDV stub → hydrated view."""

    idv_id: str
    cache_path: Path
    cache_hit: bool
    endpoint: str
    retrieved_at: str
    type_code: str | None
    type_label: str | None
    hydration_status: HydrationStatus
    local: LocalIdvRow


# === Selected Fields ===

@dataclass(frozen=True, slots=True)
class AwardSelected:
    """Parsed award-detail fields retained next to the raw payload."""

    date_signed: str | None
    total_obligation: str | None
    current_value: str | None
    potential_value: str | None
    type_code: str | None
    type_label: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "date_signed": self.date_signed,
            "total_obligation": self.total_obligation,
            "current_value": self.current_value,
            "potential_value": self.potential_value,
            "type_code": self.type_code,
            "type_label": self.type_label,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AwardSelected:
        return cls(
            date_signed=_optional_str(raw.get("date_signed")),
            total_obligation=_optional_str(raw.get("total_obligation")),
            current_value=_optional_str(raw.get("current_value")),
            potential_value=_optional_str(raw.get("potential_value")),
            type_code=_optional_str(raw.get("type_code")),
            type_label=_optional_str(raw.get("type_label")),
        )

@dataclass(frozen=True, slots=True)
class IdvSelected:
    """Parsed IDV detail fields retained next to the raw payload."""

    type_code: str | None
    type_label: str | None
    date_signed: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "type_code": self.type_code,
            "type_label": self.type_label,
            "date_signed": self.date_signed,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> IdvSelected:
        return cls(
            type_code=_optional_str(raw.get("type_code")),
            type_label=_optional_str(raw.get("type_label")),
            date_signed=_optional_str(raw.get("date_signed")),
        )


# === Client Protocol ===

@runtime_checkable
class DetailClient(Protocol):
    """Fetch a USASpending award/IDV detail JSON document."""

    def fetch_award_detail(self, source_id: str) -> dict[str, Any]:
        """Return the parsed JSON body for `GET /awards/{source_id}/`."""
        ...


# === Helpers ===

def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
