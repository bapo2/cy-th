# tests/cy_th/query/test_aggregate.py

"""Tests for `aggregate_activity` money / ranking semantics."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.query.types import ActivityWindow, AwardActivityRow, GroupBy, RecipientActivityRow


# === Helpers ===

JAN = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))
FEB = ActivityWindow(from_date=date(2025, 2, 1), to_date=date(2025, 2, 28))
FULL = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 2, 28))


# === Core Semantics ===

def test_empty_selection_returns_empty(dataset: ProcurementDataset) -> None:
    with dataset:
        assert dataset.aggregate_activity(dataset.select_awards([]), JAN) == []

def test_inclusive_date_window_and_sums(dataset: ProcurementDataset) -> None:
    with dataset:
        ids = dataset.select_awards(["A1", "A2", "A3", "A4"])
        jan = dataset.aggregate_activity(ids, JAN, group_by=GroupBy.AWARD)
        by_id = {row.award_id: row for row in jan}
        assert set(by_id) == {"A1", "A2", "A3"}  # A4 null-only excluded
        assert by_id["A1"].total_obligation == Decimal("100.00")
        assert by_id["A1"].transaction_count == 1
        assert by_id["A2"].total_obligation == Decimal("200.00")
        assert by_id["A3"].total_obligation == Decimal("75.00")
        assert by_id["A3"].transaction_count == 2  # includes null-obl txn in window

        feb = dataset.aggregate_activity(ids, FEB, group_by=GroupBy.AWARD)
        assert [row.award_id for row in feb] == ["A1"]
        assert feb[0].total_obligation == Decimal("50.00")

        full = dataset.aggregate_activity(
            dataset.select_awards(["A1"]), FULL, group_by=GroupBy.AWARD
        )
        assert full[0].total_obligation == Decimal("150.00")
        assert full[0].transaction_count == 2

def test_null_total_groups_excluded(dataset: ProcurementDataset) -> None:
    with dataset:
        rows = dataset.aggregate_activity(
            dataset.select_awards(["A4"]), JAN, group_by=GroupBy.AWARD
        )
        assert rows == []

def test_rank_order_limit_and_tiebreak(dataset: ProcurementDataset) -> None:
    with dataset:
        rows = dataset.aggregate_activity(
            dataset.select_awards(["A1", "A2", "A3"]),
            JAN,
            group_by=GroupBy.AWARD,
            limit=2,
        )
        assert isinstance(rows[0], AwardActivityRow)
        assert [row.award_id for row in rows] == ["A2", "A1"]
        assert [row.total_obligation for row in rows] == [
            Decimal("200.00"),
            Decimal("100.00"),
        ]

def test_group_by_recipient(dataset: ProcurementDataset) -> None:
    with dataset:
        rows = dataset.aggregate_activity(
            dataset.select_awards(["A1", "A2", "A3"]),
            JAN,
            group_by=GroupBy.RECIPIENT,
        )
        assert isinstance(rows[0], RecipientActivityRow)
        by_uei = {row.recipient_id: row for row in rows}
        assert set(by_uei) == {"UEI_ALPHA", "UEI_BETA"}
        # A1 (100) + A3 (75) under Alpha in January
        assert by_uei["UEI_ALPHA"].total_obligation == Decimal("175.00")
        assert by_uei["UEI_ALPHA"].name == "Alpha Corp"
        assert by_uei["UEI_BETA"].total_obligation == Decimal("200.00")
        # ranked: Beta 200, Alpha 175
        assert [row.recipient_id for row in rows] == ["UEI_BETA", "UEI_ALPHA"]

def test_result_preserves_award_provenance_fields(dataset: ProcurementDataset) -> None:
    with dataset:
        rows = dataset.aggregate_activity(
            dataset.select_awards(["A2"]), JAN, group_by=GroupBy.AWARD
        )
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, AwardActivityRow)
        assert row.piid == "PIID-A2"
        assert row.recipient_id == "UEI_BETA"
        assert row.usaspending_permalink == "https://example.test/award/A2"

def test_rejects_inverted_window_and_negative_limit(dataset: ProcurementDataset) -> None:
    with dataset:
        sel = dataset.select_awards(["A1"])
        with pytest.raises(ValueError, match="from_date"):
            dataset.aggregate_activity(
                sel,
                ActivityWindow(from_date=date(2025, 2, 1), to_date=date(2025, 1, 1)),
            )
        with pytest.raises(ValueError, match="limit"):
            dataset.aggregate_activity(sel, JAN, limit=-1)
