# tests/cy_th/schema/test_snapshot.py

"""Tests for Award topology + money-snapshot projection."""

# === Imports ===

from __future__ import annotations
from decimal import Decimal
import pytest

from cy_th.schema.enums import SnapshotSource, SnapshotStatus
from cy_th.schema.snapshot import project_award_from_transactions
from tests.factories.usaspending import (
    find_award_groups,
    snapshot_input_from_csv_row,
)


# === Guards (Invalid Inputs) ===

def test_empty_group_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        project_award_from_transactions([])


# === Award Groups ===

def test_every_real_award_group_projects(
    awards_by_id: dict[str, list[dict[str, str]]],
) -> None:
    """All award groups in the extract project without error."""

    status_counts: dict[str, int] = {}
    for _award_id, rows in awards_by_id.items():
        inputs = [snapshot_input_from_csv_row(r) for r in rows]
        inputs = [r for r in inputs if r["transaction_id"]]  # Skip malformed rows missing txn ids (shouldn't happen)
        if not inputs:
            continue
        result = project_award_from_transactions(inputs)
        status_counts[result.snapshot_status.value] = (
            status_counts.get(result.snapshot_status.value, 0) + 1
        )
        txn_ids = {str(r["transaction_id"]) for r in inputs}
        assert result.projection_transaction_id in txn_ids
        if result.snapshot_status is SnapshotStatus.DEFENSIBLE:
            assert result.snapshot_source is SnapshotSource.TRANSACTION
            assert result.snapshot_transaction_id in txn_ids
            assert result.observed_total_obligation is not None
            assert result.observed_current_value is not None
            assert result.observed_potential_value is not None
        else:
            assert result.observed_total_obligation is None
            assert result.observed_current_value is None
            assert result.observed_potential_value is None

    assert status_counts.get("defensible", 0) > 0
    assert sum(status_counts.values()) > 0

def test_multi_txn_award_topology_uses_latest_action_date(
    awards_by_id: dict[str, list[dict[str, str]]],
) -> None:
    multi = find_award_groups(awards_by_id, min_txns=2)
    assert multi, "expected at least one multi-transaction award in extract"

    award_id, rows = multi[0]
    inputs = [snapshot_input_from_csv_row(r) for r in rows]
    result = project_award_from_transactions(inputs)

    # Topology = max action_date, then min transaction_id
    best_date = max(str(r["action_date"]) for r in inputs)
    expected_ids = sorted(
        str(r["transaction_id"])
        for r in inputs
        if str(r["action_date"]) == best_date
    )
    assert result.projection_transaction_id == expected_ids[0]
    assert award_id  # Readability / failure context


# === Edge Cases ===
# NOTE: These have been derived from real row shapes during research

def test_eligibility_and_conflict_using_real_row_template(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    """Clone a real row's shape to exercise rare snapshot branches safely."""

    base = snapshot_input_from_csv_row(prime_txn_sample[0])
    assert base["transaction_id"]

    # Ineligible-only → requires_enrichment / none (topology is still set)
    ineligible = {
        **base,
        "transaction_number": "2",
        "total_dollars_obligated": "10",
        "current_total_value_of_award": "10",
        "potential_total_value_of_award": "10",
    }
    r = project_award_from_transactions([ineligible])
    assert r.snapshot_status is SnapshotStatus.REQUIRES_ENRICHMENT
    assert r.snapshot_source is SnapshotSource.NONE
    assert r.projection_transaction_id == base["transaction_id"]

    # All-null money on eligible row → not_observed
    null_money = {
        **base,
        "transaction_number": "0",
        "total_dollars_obligated": "",
        "current_total_value_of_award": "",
        "potential_total_value_of_award": "",
    }
    r = project_award_from_transactions([null_money])
    assert r.snapshot_status is SnapshotStatus.NOT_OBSERVED
    assert r.snapshot_source is SnapshotSource.TRANSACTION

    # Conflict on same day between two eligible clones
    a = {
        **base,
        "transaction_id": f"{base['transaction_id']}_A",
        "transaction_number": "0",
        "total_dollars_obligated": "100",
        "current_total_value_of_award": "100",
        "potential_total_value_of_award": "100",
    }
    b = {
        **base,
        "transaction_id": f"{base['transaction_id']}_B",
        "transaction_number": "0",
        "total_dollars_obligated": "100",
        "current_total_value_of_award": "100",
        "potential_total_value_of_award": "200",
    }
    r = project_award_from_transactions([a, b])
    assert r.snapshot_status is SnapshotStatus.REQUIRES_ENRICHMENT
    assert r.snapshot_source is SnapshotSource.NONE

    # Defensible agreement
    b_ok = {**b, "potential_total_value_of_award": "100"}
    r = project_award_from_transactions([a, b_ok])
    assert r.snapshot_status is SnapshotStatus.DEFENSIBLE
    assert r.observed_total_obligation == Decimal("100")
    assert r.snapshot_transaction_id == min(a["transaction_id"], b_ok["transaction_id"])

def test_partial_nulls_require_enrichment(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    base = snapshot_input_from_csv_row(prime_txn_sample[0])
    partial = {
        **base,
        "transaction_number": "0",
        "total_dollars_obligated": "10",
        "current_total_value_of_award": "",
        "potential_total_value_of_award": "10",
    }
    r = project_award_from_transactions([partial])
    assert r.snapshot_status is SnapshotStatus.REQUIRES_ENRICHMENT
    assert r.snapshot_source is SnapshotSource.NONE

def test_snapshot_parsing_guards(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    base = snapshot_input_from_csv_row(prime_txn_sample[0])
    with pytest.raises(ValueError, match="transaction_id"):
        project_award_from_transactions([{**base, "transaction_id": ""}])
    with pytest.raises(ValueError, match="action_date"):
        project_award_from_transactions([{**base, "action_date": None}])
    with pytest.raises(ValueError, match="invalid action_date"):
        project_award_from_transactions([{**base, "action_date": "not-a-date"}])
    with pytest.raises(ValueError, match="invalid money"):
        project_award_from_transactions(
            [{
                **base,
                "transaction_number": "0",
                "total_dollars_obligated": "abc",
                "current_total_value_of_award": "1",
                "potential_total_value_of_award": "1",
            }]
        )
