# tests/cy_th/query/test_open.py

"""Tests for opening a pinned published procurement dataset."""

# === Imports ===

from __future__ import annotations
from datetime import date
from pathlib import Path
import pytest

from cy_th.materialize.paths import current_path, write_current_atomic
from cy_th.materialize.publish import TRANSACTIONS_PARQUET
from cy_th.query.dataset import ProcurementDataset
from cy_th.query.errors import (
    IncompleteDatasetError,
    InvalidRunIdError,
    MissingCurrentError,
    StaleSelectionError,
)
from cy_th.query.types import ActivityWindow


# === Success ===

def test_open_resolves_current_and_registers_views(query_data_root: Path) -> None:
    with ProcurementDataset.open(query_data_root) as ds:
        assert ds.run_id == "20260914T180000Z_abcdef"
        assert ds.opened.run_id == ds.run_id
        assert ds.set_path == query_data_root / "sets" / ds.run_id
        n_txn = ds.conn.execute("SELECT COUNT(*) FROM transaction_fact").fetchone()
        n_awd = ds.conn.execute("SELECT COUNT(*) FROM award_record").fetchone()
        assert n_txn is not None and n_txn[0] == 6
        assert n_awd is not None and n_awd[0] == 4

def test_open_session_stays_pinned_when_current_changes(query_data_root: Path) -> None:
    with ProcurementDataset.open(query_data_root) as ds:
        pinned = ds.run_id
        current_path(query_data_root).write_text("not-a-run-id\n", encoding="utf-8")
        assert ds.run_id == pinned
        n = ds.conn.execute("SELECT COUNT(*) FROM transaction_fact").fetchone()
        assert n is not None and n[0] == 6
        write_current_atomic(query_data_root, pinned)

def test_closed_dataset_rejects_conn_access(query_data_root: Path) -> None:
    ds = ProcurementDataset.open(query_data_root)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = ds.conn

def test_selection_bound_to_session(query_data_root: Path) -> None:
    with ProcurementDataset.open(query_data_root) as ds:
        sel = ds.select_awards(["A1"])
        assert sel.session_id == ds.session_id
        assert ds.award_ids(sel) == frozenset({"A1"})

def test_selection_rejected_across_sessions(query_data_root: Path) -> None:
    with ProcurementDataset.open(query_data_root) as a:
        sel = a.select_awards(["A1"])
        with ProcurementDataset.open(query_data_root) as b:
            assert a.session_id != b.session_id
            with pytest.raises(StaleSelectionError, match="different query session"):
                b.award_ids(sel)
            with pytest.raises(StaleSelectionError, match="different query session"):
                b.aggregate_activity(sel, ActivityWindow(date(2025, 1, 1), date(2025, 12, 31)))

def test_selection_rejected_after_close(query_data_root: Path) -> None:
    ds = ProcurementDataset.open(query_data_root)
    sel = ds.select_awards(["A1"])
    ds.close()
    with pytest.raises(StaleSelectionError, match="closed"):
        ds.award_ids(sel)
    with pytest.raises(StaleSelectionError, match="closed"):
        ds.aggregate_activity(sel, ActivityWindow(date(2025, 1, 1), date(2025, 12, 31)))


# === Failures ===

def test_open_missing_current(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(MissingCurrentError):
        ProcurementDataset.open(root)

def test_open_invalid_run_id(tmp_path: Path) -> None:
    root = tmp_path / "bad"
    root.mkdir()
    (root / "CURRENT").write_text("nope\n", encoding="utf-8")
    with pytest.raises(InvalidRunIdError):
        ProcurementDataset.open(root)

def test_open_incomplete_set_missing_parquet(query_data_root: Path) -> None:
    set_path = query_data_root / "sets" / "20260914T180000Z_abcdef"
    txn = set_path / TRANSACTIONS_PARQUET
    backup = txn.with_suffix(".parquet.bak")
    txn.rename(backup)
    try:
        with pytest.raises(IncompleteDatasetError, match="transactions.parquet"):
            ProcurementDataset.open(query_data_root)
    finally:
        backup.rename(txn)
