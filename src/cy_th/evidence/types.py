# cy_th/evidence/types.py

"""Typed models for the evidence tool layer (refs, cards, retained evidence, views)."""

# === Imports ===

from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping

from cy_th.query.types import (
    AwardActivityRow,
    GroupBy,
    RecipientActivityRow,
    RelatedEntity,
)


# === Bounds ===

DEFAULT_SEMANTIC_TOP_K: int = 10
MAX_SEMANTIC_TOP_K: int = 50

DEFAULT_AGGREGATE_LIMIT: int = 10
MAX_AGGREGATE_LIMIT: int = 100

DEFAULT_AWARD_CARD_LIMIT: int = 10
MAX_AWARD_CARD_LIMIT: int = 50

DEFAULT_TRAVERSAL_LIMIT: int = 50
MAX_TRAVERSAL_LIMIT: int = 200


def clamp_bound(value: int, *, maximum: int, name: str) -> int:
    """Reject non-positive limits; clamp to `maximum` for model-visible payloads."""

    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return min(value, maximum)


# === Refs ===

@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Opaque session-local reference to an internal Award selection."""

    id: str

    def __str__(self) -> str:
        return self.id

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id}


# === Award Citation Card ===

@dataclass(frozen=True, slots=True)
class PlaceOfPerformanceSummary:
    """Compact PoP geo summary for an Award card."""

    location_id: str | None = None
    country_code: str | None = None
    state_code: str | None = None
    county_fips: str | None = None
    city_name: str | None = None
    zip_code: str | None = None
    granularity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_dict(self)

@dataclass(frozen=True, slots=True)
class AwardCard:
    """Source-backed Award citation card for grounding / permalinks."""

    award_id: str
    piid: str | None = None
    award_type_code: str | None = None
    recipient_id: str | None = None
    recipient_name: str | None = None
    base_description: str | None = None
    awarding_agency_id: str | None = None
    awarding_agency_name: str | None = None
    awarding_sub_agency_id: str | None = None
    awarding_sub_agency_name: str | None = None
    awarding_office_id: str | None = None
    awarding_office_name: str | None = None
    naics_id: str | None = None
    naics_code: str | None = None
    naics_description: str | None = None
    psc_id: str | None = None
    psc_code: str | None = None
    psc_description: str | None = None
    place_of_performance: PlaceOfPerformanceSummary | None = None
    usaspending_permalink: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = _public_dict(self)
        pop = self.place_of_performance
        raw["place_of_performance"] = None if pop is None else pop.to_dict()
        return raw


# === Retained Evidence ===

@dataclass(frozen=True, slots=True)
class SemanticHitEvidence:
    """Retrieval-specific semantic hit (not folded into `AwardCard`)."""

    award_id: str
    score: float
    text: str
    document_id: str
    query: str

    def to_dict(self) -> dict[str, Any]:
        return _public_dict(self)

@dataclass(frozen=True, slots=True)
class AggregateEvidence:
    """Retained aggregation result tied to the selection it was derived from."""

    derived_from: SelectionRef
    group_by: GroupBy
    rows: tuple[AwardActivityRow, ...] | tuple[RecipientActivityRow, ...]

@dataclass(frozen=True, slots=True)
class TraversalEvidence:
    """Retained one-hop traversal result tied to the selection it was derived from."""

    derived_from: SelectionRef
    entities: tuple[RelatedEntity, ...]


# === Model-Visible Views ===

@dataclass(frozen=True, slots=True)
class SearchResultView:
    """Bounded semantic search result + minted selection ref."""

    selection: SelectionRef
    count: int
    hits: tuple[SemanticHitEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_dict(),
            "count": self.count,
            "hits": [h.to_dict() for h in self.hits],
        }

@dataclass(frozen=True, slots=True)
class ResolveResultView:
    """Bounded structured resolve result + minted selection ref."""

    selection: SelectionRef
    count: int
    preview: tuple[AwardCard, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_dict(),
            "count": self.count,
            "preview": [c.to_dict() for c in self.preview],
        }

@dataclass(frozen=True, slots=True)
class AggregateResultView:
    """Bounded aggregation view over a selection."""

    derived_from: SelectionRef
    group_by: GroupBy
    rows: tuple[AwardActivityRow, ...] | tuple[RecipientActivityRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_from": self.derived_from.to_dict(),
            "group_by": self.group_by.value,
            "rows": [_row_dict(r) for r in self.rows],
        }

@dataclass(frozen=True, slots=True)
class TraversalResultView:
    """Bounded traversal view over a selection."""

    derived_from: SelectionRef
    entities: tuple[RelatedEntity, ...]
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_from": self.derived_from.to_dict(),
            "entities": [_public_dict(e) for e in self.entities],
            "truncated": self.truncated,
        }

@dataclass(frozen=True, slots=True)
class AwardEvidenceView:
    """Bounded Award citation cards."""

    cards: tuple[AwardCard, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"cards": [c.to_dict() for c in self.cards]}


# === Helpers ===

def _public_dict(obj: object) -> dict[str, Any]:
    """`asdict` with enums → value and Decimals → str for stable JSON-ish payloads."""

    raw = asdict(obj)  # type: ignore[arg-type]
    return _normalize(raw)

def _row_dict(
    row: AwardActivityRow | RecipientActivityRow,
) -> dict[str, Any]:
    return _public_dict(row)

def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and value.__class__.__name__ != "type":
        # StrEnum or similar
        try:
            from enum import Enum

            if isinstance(value, Enum):
                return value.value
        except Exception:
            pass
    return value
