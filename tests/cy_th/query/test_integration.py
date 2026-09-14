# tests/cy_th/query/test_integration.py

"""End-to-end resolve → aggregate composition over published sets."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path

from cy_th.query.dataset import ProcurementDataset
from cy_th.query.types import (
    ActivityWindow,
    AwardFilters,
    GroupBy,
    LocationFilter,
    RelationRole,
)
from cy_th.schema.enums import ClassificationKind
from cy_th.schema.keys import classification_id


# === Composition ===

def test_resolve_then_aggregate_pop_filter(dataset: ProcurementDataset) -> None:
    """PoP VA awards → January obligations ranked by Award."""

    window = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))
    with dataset:
        selection = dataset.resolve_awards(
            AwardFilters(
                location=LocationFilter(
                    role=RelationRole.PLACE_OF_PERFORMANCE,
                    state_code="VA",
                )
            )
        )
        assert dataset.award_ids(selection) == frozenset({"A1"})
        rows = dataset.aggregate_activity(selection, window, group_by=GroupBy.AWARD)
        assert len(rows) == 1
        assert rows[0].award_id == "A1"
        assert rows[0].total_obligation == Decimal("100.00")

def test_resolve_naics_and_aggregate_by_recipient(dataset: ProcurementDataset) -> None:
    window = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 2, 28))
    naics = classification_id(ClassificationKind.NAICS, "541330")
    with dataset:
        selection = dataset.resolve_awards(AwardFilters(naics_ids=[naics]))
        assert dataset.award_ids(selection) == frozenset({"A1", "A3"})
        rows = dataset.aggregate_activity(
            selection,
            window,
            group_by=GroupBy.RECIPIENT,
        )
        assert len(rows) == 1
        assert rows[0].recipient_id == "UEI_ALPHA"
        # A1 full window (150) + A3 (75)
        assert rows[0].total_obligation == Decimal("225.00")

def test_real_extract_resolve_aggregate_smoke(
    tmp_path: Path,
    prime_txn_csv_path: Path,
) -> None:
    """Published real-day extract opens and supports resolve + aggregate."""

    from cy_th.materialize.pipeline import materialize
    from cy_th.schema.enums import AgencyTier
    from cy_th.schema.keys import agency_id

    out = tmp_path / "real"
    materialize(
        [prime_txn_csv_path],
        out=out,
        run_id="20260914T190000Z_aa11bb",
    )
    
    # Infer `action_date` from the extract filename when possible (else wide window)
    name = prime_txn_csv_path.name
    day = name.removeprefix("prime_txns_").removesuffix(".csv")
    try:
        y, m, d = (int(p) for p in day.split("-"))
        window = ActivityWindow(from_date=date(y, m, d), to_date=date(y, m, d))
    except ValueError:
        window = ActivityWindow(from_date=date(2020, 1, 1), to_date=date(2030, 1, 1))

    dod = agency_id(tier=AgencyTier.TOPTIER, code="097")
    with ProcurementDataset.open(out) as ds:
        count_row = ds.conn.execute("SELECT COUNT(*) FROM transaction_fact").fetchone()
        assert count_row is not None and count_row[0] > 0
        selection = ds.resolve_awards(AwardFilters(awarding_agency_ids=[dod]))
        assert selection.count > 0
        top = ds.aggregate_activity(
            selection,
            window,
            group_by=GroupBy.AWARD,
            limit=5,
        )
        assert len(top) == 5
        totals = [row.total_obligation for row in top]
        assert totals == sorted(totals, reverse=True)
        assert all(row.award_id for row in top)
