# tests/cy_th/materialize/test_awards.py

"""Tests for `AwardRecord` DuckDB reduce vs. `snapshot.py` oracle."""

# === Imports ===

from __future__ import annotations
from decimal import Decimal
from pathlib import Path

from cy_th.materialize.awards import TABLE_AWARDS, materialize_awards
from cy_th.materialize.load import connect_staging, load_projected_csvs
from cy_th.materialize.validate import validate_and_dedupe
from cy_th.schema.enums import SnapshotSource, SnapshotStatus
from cy_th.schema.snapshot import project_award_from_transactions
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Helpers ===

def _money_row(
    *,
    txn_id: str,
    award_id: str,
    action_date: str,
    txn_number: str = "0",
    obl: str = "",
    current: str = "",
    potential: str = "",
    **extra: str,
) -> dict[str, str]:
    return blank_projected_row(
        contract_transaction_unique_key=txn_id,
        contract_award_unique_key=award_id,
        action_date=action_date,
        transaction_number=txn_number,
        total_dollars_obligated=obl,
        current_total_value_of_award=current,
        potential_total_value_of_award=potential,
        **extra,
    )

def _oracle_input(row: dict[str, str]) -> dict[str, object]:
    return {
        "transaction_id": row["contract_transaction_unique_key"],
        "action_date": row["action_date"],
        "transaction_number": row["transaction_number"] or None,
        "total_dollars_obligated": row["total_dollars_obligated"] or None,
        "current_total_value_of_award": row["current_total_value_of_award"] or None,
        "potential_total_value_of_award": row["potential_total_value_of_award"] or None,
    }

def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))

def _materialize_awards(tmp_path: Path, rows: list[dict[str, str]]):
    csv_path = write_projected_csv(tmp_path / "awards.csv", rows)
    conn = connect_staging(tmp_path / "awards.duckdb")
    load_projected_csvs(conn, [csv_path])
    validate_and_dedupe(conn)
    materialize_awards(conn)
    return conn


# === Oracle Parity Fixtures ===

def test_award_reduce_matches_snapshot_oracle_fixtures(tmp_path: Path) -> None:
    """Test that the `AwardRecord` reduce matches the `snapshot.py` oracle."""
    
    rows = [
        # Defensible (two agreeing eligible on latest day; ineligible older ignored for money)
        _money_row(
            txn_id="D2",
            award_id="A_DEF",
            action_date="2025-02-01",
            obl="10",
            current="20",
            potential="30",
        ),
        _money_row(
            txn_id="D1",
            award_id="A_DEF",
            action_date="2025-02-01",
            obl="10",
            current="20",
            potential="30",
        ),
        _money_row(
            txn_id="D3",
            award_id="A_DEF",
            action_date="2025-01-01",
            txn_number="1",
            obl="999",
            current="999",
            potential="999",
            award_id_piid="PIID_OLD",
        ),
        
        # Not observed
        _money_row(txn_id="N1", award_id="A_NO", action_date="2025-03-01"),
        
        # Conflict
        _money_row(
            txn_id="C1",
            award_id="A_CF",
            action_date="2025-04-01",
            obl="1",
            current="2",
            potential="3",
        ),
        _money_row(
            txn_id="C2",
            award_id="A_CF",
            action_date="2025-04-01",
            obl="9",
            current="2",
            potential="3",
        ),
        
        # Partial nulls
        _money_row(
            txn_id="P1",
            award_id="A_PART",
            action_date="2025-05-01",
            obl="10",
            potential="30",
        ),
        
        # No eligible
        _money_row(
            txn_id="E1",
            award_id="A_NE",
            action_date="2025-06-01",
            txn_number="2",
            obl="10",
            current="20",
            potential="30",
            award_id_piid="PIID_NE",
        ),
        
        # Topology tie → min txn ID
        _money_row(
            txn_id="Z2",
            award_id="A_TOP",
            action_date="2025-07-01",
            txn_number="1",
            award_id_piid="PIID_Z2",
        ),
        _money_row(
            txn_id="Z1",
            award_id="A_TOP",
            action_date="2025-07-01",
            txn_number="1",
            award_id_piid="PIID_Z1",
        ),
    ]

    conn = _materialize_awards(tmp_path, rows)

    by_award: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_award.setdefault(row["contract_award_unique_key"], []).append(row)

    for award_id, group in by_award.items():
        oracle = project_award_from_transactions([_oracle_input(r) for r in group])
        got = conn.execute(
            f"""
            SELECT projection_transaction_id, snapshot_status, snapshot_source,
                   snapshot_transaction_id,
                   observed_total_obligation, observed_current_value,
                   observed_potential_value, date_signed
            FROM "{TABLE_AWARDS}"
            WHERE award_id = ?
            """,
            [award_id],
        ).fetchone()
        assert got is not None, award_id
        assert got[0] == oracle.projection_transaction_id
        assert got[1] == oracle.snapshot_status.value
        assert got[2] == oracle.snapshot_source.value
        assert got[3] == oracle.snapshot_transaction_id
        assert _dec(got[4]) == oracle.observed_total_obligation
        assert _dec(got[5]) == oracle.observed_current_value
        assert _dec(got[6]) == oracle.observed_potential_value
        assert got[7] is None

    piid_row = conn.execute(
        f'SELECT piid FROM "{TABLE_AWARDS}" WHERE award_id = ?',
        ["A_TOP"],
    ).fetchone()
    assert piid_row is not None
    assert piid_row[0] == "PIID_Z1"

def test_award_statuses_cover_locked_outcomes(tmp_path: Path) -> None:
    """Spot-check enum outcomes without re-deriving the full oracle table."""

    conn = _materialize_awards(
        tmp_path,
        [
            _money_row(
                txn_id="D1",
                award_id="A_DEF",
                action_date="2025-01-01",
                obl="1",
                current="1",
                potential="1",
            ),
            _money_row(txn_id="N1", award_id="A_NO", action_date="2025-01-01"),
        ],
    )
    statuses = {
        row[0]: row[1]
        for row in conn.execute(
            f'SELECT award_id, snapshot_status FROM "{TABLE_AWARDS}"'
        ).fetchall()
    }
    assert statuses["A_DEF"] == SnapshotStatus.DEFENSIBLE.value
    assert statuses["A_NO"] == SnapshotStatus.NOT_OBSERVED.value

    source_row = conn.execute(
        f"""
        SELECT snapshot_source FROM "{TABLE_AWARDS}"
        WHERE award_id = 'A_DEF'
        """
    ).fetchone()
    assert source_row is not None
    assert source_row[0] == SnapshotSource.TRANSACTION.value
