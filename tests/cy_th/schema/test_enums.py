# tests/cy_th/schema/test_enums.py

"""Tests for canonical schema enumerations."""

# === Imports ===

from cy_th.schema.enums import (
    AgencyTier,
    ClassificationKind,
    HydrationStatus,
    SnapshotSource,
    SnapshotStatus,
)


# === Snapshot ===

def test_snapshot_status_values() -> None:
    assert {m.value for m in SnapshotStatus} == {
        "defensible",
        "requires_enrichment",
        "not_observed",
    }

def test_snapshot_source_values() -> None:
    assert {m.value for m in SnapshotSource} == {
        "transaction",
        "award_detail",
        "none",
    }


# === Agency / Classification / IDV ===

def test_agency_tier_values() -> None:
    assert AgencyTier.TOPTIER.value == "toptier"
    assert AgencyTier.SUBTIER.value == "subtier"

def test_classification_kind_values() -> None:
    assert ClassificationKind.NAICS.value == "NAICS"
    assert ClassificationKind.PSC.value == "PSC"

def test_hydration_status_values() -> None:
    assert HydrationStatus.STUB.value == "stub"
    assert HydrationStatus.HYDRATED.value == "hydrated"
