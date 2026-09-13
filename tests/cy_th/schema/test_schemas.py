# tests/cy_th/schema/test_schemas.py

"""Tests for logical record schema shapes (refs, `TransactionFact`, `AwardRecord`)."""

# === Imports ===

from cy_th.schema.award import AWARD_RECORD_SCHEMA
from cy_th.schema.references import (
    AGENCY_REF_SCHEMA,
    CLASSIFICATION_REF_SCHEMA,
    IDV_REF_SCHEMA,
    LOCATION_REF_SCHEMA,
    OFFICE_REF_SCHEMA,
    RECIPIENT_REF_SCHEMA,
)
from cy_th.schema.transaction import TRANSACTION_FACT_SCHEMA
from cy_th.schema.types import Schema


# === Helpers ===

def _names(schema: Schema) -> list[str]:
    return [c.name for c in schema]

def _assert_unique_pk(schema: Schema, pk: str) -> None:
    names = _names(schema)
    assert len(names) == len(set(names))
    assert pk in names
    assert not next(c for c in schema if c.name == pk).nullable


# === Refs ===

def test_reference_schema_primary_keys() -> None:
    specs = {
        "AgencyRef": (AGENCY_REF_SCHEMA, "agency_id"),
        "OfficeRef": (OFFICE_REF_SCHEMA, "office_id"),
        "RecipientRef": (RECIPIENT_REF_SCHEMA, "uei"),
        "ClassificationRef": (CLASSIFICATION_REF_SCHEMA, "classification_id"),
        "IDVRef": (IDV_REF_SCHEMA, "idv_id"),
        "LocationRef": (LOCATION_REF_SCHEMA, "location_id"),
    }
    for _label, (schema, pk) in specs.items():
        _assert_unique_pk(schema, pk)


# === Facts ===

def test_transaction_fact_required_columns() -> None:
    required = {c.name for c in TRANSACTION_FACT_SCHEMA if not c.nullable}
    assert required == {"transaction_id", "award_id", "action_date"}
    assert "federal_action_obligation" in _names(TRANSACTION_FACT_SCHEMA)

def test_award_record_required_and_fk_surface() -> None:
    required = {c.name for c in AWARD_RECORD_SCHEMA if not c.nullable}
    assert required == {
        "award_id",
        "projection_transaction_id",
        "snapshot_status",
        "snapshot_source",
    }
    names = set(_names(AWARD_RECORD_SCHEMA))
    for fk in (
        "recipient_id",
        "awarding_agency_id",
        "awarding_sub_agency_id",
        "awarding_office_id",
        "funding_agency_id",
        "funding_sub_agency_id",
        "funding_office_id",
        "parent_idv_id",
        "naics_id",
        "psc_id",
        "recipient_location_id",
        "place_of_performance_id",
    ):
        assert fk in names
    for money in (
        "observed_total_obligation",
        "observed_current_value",
        "observed_potential_value",
        "date_signed",
    ):
        assert next(c for c in AWARD_RECORD_SCHEMA if c.name == money).nullable
