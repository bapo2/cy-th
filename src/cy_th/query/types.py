# cy_th/query/types.py

"""Typed filter and result models for the procurement query runtime."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from cy_th.schema.enums import AgencyTier, ClassificationKind


# === Enums ===

class LocationRole(StrEnum):
    """Which Award location FK a `LocationFilter` applies to."""

    RECIPIENT = "recipient"
    PLACE_OF_PERFORMANCE = "place_of_performance"

class GroupBy(StrEnum):
    """Aggregation grouping for `aggregate_activity`."""

    AWARD = "award"
    RECIPIENT = "recipient"

class EntityKind(StrEnum):
    """Canonical entity kinds returned by relationship traversal.

    Declaration order is the primary sort key for `TraversalResult.entities`.
    """

    RECIPIENT = "recipient"
    AGENCY = "agency"
    OFFICE = "office"
    IDV = "idv"
    LOCATION = "location"
    CLASSIFICATION = "classification"

class RelationRole(StrEnum):
    """Procurement role on a traversal edge when the Award FK is role-typed.

    Declaration order is the secondary sort key after `None` roles sort first.
    """

    AWARDING = "awarding"
    FUNDING = "funding"
    RECIPIENT = "recipient"
    PLACE_OF_PERFORMANCE = "place_of_performance"


# === Filters ===

@dataclass(frozen=True, slots=True)
class LocationFilter:
    """Exact location predicate against projected Award topology.

    Set either `location_ids` or one/more structured fields (not fuzzy matching). Structured fields AND'd together when multiple are provided.
    """

    role: LocationRole
    location_ids: Sequence[str] | None = None
    country_code: str | None = None
    state_code: str | None = None
    county_fips: str | None = None
    city_name: str | None = None
    zip_code: str | None = None

@dataclass(frozen=True, slots=True)
class AwardFilters:
    """Award/ref predicates for `resolve_awards`.

    Each list field uses `None` for unconstrained and `[]` for zero matches. All active predicates are AND'd.
    """

    award_ids: Sequence[str] | None = None
    recipient_ids: Sequence[str] | None = None
    awarding_agency_ids: Sequence[str] | None = None
    awarding_sub_agency_ids: Sequence[str] | None = None
    awarding_office_ids: Sequence[str] | None = None
    funding_agency_ids: Sequence[str] | None = None
    funding_sub_agency_ids: Sequence[str] | None = None
    funding_office_ids: Sequence[str] | None = None
    naics_ids: Sequence[str] | None = None
    psc_ids: Sequence[str] | None = None
    location: LocationFilter | None = None

@dataclass(frozen=True, slots=True)
class ActivityWindow:
    """Inclusive transaction activity bounds on `transaction_fact.action_date`."""

    from_date: date
    to_date: date

@dataclass(frozen=True, slots=True)
class AwardSelection:
    """Session-scoped set of qualifying Award IDs backed by a DuckDB temp relation.

    Produced by `resolve_awards` / `select_awards` on one `ProcurementDataset` session. Valid only for that open session (`session_id` must match).
    """

    relation_name: str
    count: int
    session_id: str


# === Aggregation Results ===

@dataclass(frozen=True, slots=True)
class AwardActivityRow:
    """One ranked Award aggregation row."""

    award_id: str
    total_obligation: Decimal
    transaction_count: int
    recipient_id: str | None
    piid: str | None
    usaspending_permalink: str | None

@dataclass(frozen=True, slots=True)
class RecipientActivityRow:
    """One ranked recipient aggregation row."""

    recipient_id: str
    total_obligation: Decimal
    transaction_count: int
    name: str | None


# === Traversal Results ===

@dataclass(frozen=True, slots=True)
class RelatedEntity:
    """One deduped related canonical entity from one-hop Award relationship traversal."""

    kind: EntityKind
    role: RelationRole | None
    entity_id: str
    label: str | None = None
    agency_tier: AgencyTier | None = None
    idv_agency_id: str | None = None
    classification_kind: ClassificationKind | None = None
    code: str | None = None
    description: str | None = None
    country_code: str | None = None
    state_code: str | None = None
    county_fips: str | None = None
    city_name: str | None = None
    zip_code: str | None = None
    granularity: str | None = None

@dataclass(frozen=True, slots=True)
class TraversalResult:
    """Flat, deterministically ordered related entities from `traverse_relationships`."""

    entities: tuple[RelatedEntity, ...]
