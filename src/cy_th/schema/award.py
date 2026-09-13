# cy_th/schema/award.py

"""Logical column contract for durable local Award records."""

# === Imports ===

from cy_th.schema.types import (
    DATE,
    MONEY,
    STRING,
    Schema,
    column,
    enum_type,
)


# === Shared Enum Types ===

_SNAPSHOT_STATUS = enum_type("SnapshotStatus")
_SNAPSHOT_SOURCE = enum_type("SnapshotSource")


# === AwardRecord ===

AWARD_RECORD_SCHEMA: Schema = (
    
    # Identity components
    column(
        "award_id",
        STRING,
        nullable=False,
        description="Primary key USASpending `contract_award_unique_key`",
    ),
    column(
        "piid",
        STRING,
        nullable=True,
        description="Human-readable procurement ID (`award_id_piid`)",
    ),
    column(
        "award_type_code",
        STRING,
        nullable=True,
        description="Contract type code (`A`/`B`/`C`/`D` in the primary population).",
    ),
    
    # Topology FKs (role-typed; roles shouldn't collapse!)
    column(
        "recipient_id",
        STRING,
        nullable=True,
        description="FK → `RecipientRef.uei`",
    ),
    column(
        "awarding_agency_id",
        STRING,
        nullable=True,
        description="FK → toptier `AgencyRef.agency_id` (awarding role)",
    ),
    column(
        "awarding_sub_agency_id",
        STRING,
        nullable=True,
        description="FK → subtier `AgencyRef.agency_id` (awarding role)",
    ),
    column(
        "awarding_office_id",
        STRING,
        nullable=True,
        description="FK → `OfficeRef.office_id` (awarding role; null if office code absent)",
    ),
    column(
        "funding_agency_id",
        STRING,
        nullable=True,
        description="FK → toptier `AgencyRef.agency_id` (funding role)",
    ),
    column(
        "funding_sub_agency_id",
        STRING,
        nullable=True,
        description="FK → subtier `AgencyRef.agency_id` (funding role)",
    ),
    column(
        "funding_office_id",
        STRING,
        nullable=True,
        description="FK → `OfficeRef.office_id` (funding role; null if office code absent)",
    ),
    column(
        "parent_idv_id",
        STRING,
        nullable=True,
        description="FK → `IDVRef.idv_id` (when a parent vehicle is present)",
    ),
    column(
        "naics_id",
        STRING,
        nullable=True,
        description="FK → `ClassificationRef.classification_id` (`NAICS:...`)",
    ),
    column(
        "psc_id",
        STRING,
        nullable=True,
        description="FK → `ClassificationRef.classification_id` (`PSC:...`)",
    ),
    column(
        "recipient_location_id",
        STRING,
        nullable=True,
        description="FK → `LocationRef.location_id` (recipient location role)",
    ),
    column(
        "place_of_performance_id",
        STRING,
        nullable=True,
        description="FK → `LocationRef.location_id` (place-of-performance role)",
    ),
    
    # Semantics components
    column(
        "base_description",
        STRING,
        nullable=True,
        description="Award base description (`prime_award_base_transaction_description`)",
    ),
    column(
        "usaspending_permalink",
        STRING,
        nullable=True,
        description="USASpending citation URL (`usaspending_permalink`)",
    ),
    column(
        "pop_start",
        DATE,
        nullable=True,
        description="Period of performance start from the topology projection row",
    ),
    column(
        "pop_end",
        DATE,
        nullable=True,
        description="Current PoP end (`period_of_performance_current_end_date` only)",
    ),
    
    # Projection provenance
    column(
        "projection_transaction_id",
        STRING,
        nullable=False,
        description="Txn chosen for topology/semantics (`MAX(action_date)`, then txn key)",
    ),
    
    # Observed money (local population)
    column(
        "observed_total_obligation",
        MONEY,
        nullable=True,
        description="Defensible `total_dollars_obligated`, else null",
    ),
    column(
        "observed_current_value",
        MONEY,
        nullable=True,
        description="Defensible `current_total_value_of_award`, else null",
    ),
    column(
        "observed_potential_value",
        MONEY,
        nullable=True,
        description="Defensible `potential_total_value_of_award`, else null",
    ),
    column(
        "snapshot_status",
        _SNAPSHOT_STATUS,
        nullable=False,
        description="Quality of observed money state (`defensible` / ...)",
    ),
    column(
        "snapshot_source",
        _SNAPSHOT_SOURCE,
        nullable=False,
        description="Provenance of money snapshot (`transaction` / `award_detail` / `none`)",
    ),
    column(
        "snapshot_transaction_id",
        STRING,
        nullable=True,
        description="Representative eligible txn when a defensible snapshot exists",
    ),
    
    # Reserved enrichment
    column(
        "date_signed",
        DATE,
        nullable=True,
        description="Award signing / base date (null on txn-only first materialize)",
    ),
)
"""Durable local Award object (identity, topology, semantics, optional money).

Recomputed from the union of local `TransactionFact` rows for `award_id` (avoiding last-shard-wins). For topology/semantics and money snapshot, we use separate rules.
"""
