# tests/cy_th/materialize/test_load_validate.py

"""Tests for CSV load, header checks, casts, rejects, and dedupe."""

# === Imports ===

from __future__ import annotations
import csv
from pathlib import Path
import pytest

from cy_th.materialize.load import (
    TABLE_RAW,
    assert_projected_header,
    connect_staging,
    load_projected_csvs,
    read_csv_header,
)
from cy_th.materialize.validate import (
    TABLE_REJECTS,
    TABLE_VALID,
    validate_and_dedupe,
)
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Headers ===

def test_assert_projected_header_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "dup.csv"
    path.write_text("a,a\n1,2\n", encoding="utf-8")
    header = read_csv_header(path)
    with pytest.raises(ValueError, match="duplicate"):
        assert_projected_header(path, header)

def test_assert_projected_header_rejects_missing(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    path.write_text("contract_transaction_unique_key\nx\n", encoding="utf-8")
    header = read_csv_header(path)
    with pytest.raises(ValueError, match="missing required"):
        assert_projected_header(path, header)

def test_load_requires_at_least_one_path(tmp_path: Path) -> None:
    conn = connect_staging(tmp_path / "empty.duckdb")
    with pytest.raises(ValueError, match="at least one"):
        load_projected_csvs(conn, [])


# === Load + Validate ===

def test_load_and_validate_happy_path(tmp_path: Path) -> None:
    csv_path = write_projected_csv(
        tmp_path / "ok.csv",
        [
            blank_projected_row(
                contract_transaction_unique_key="T1",
                federal_action_obligation="12.50",
                action_date="2025-02-01",
            ),
        ],
    )
    conn = connect_staging(tmp_path / "ok.duckdb")
    load = load_projected_csvs(conn, [csv_path])
    assert load.input_files == 1
    assert load.rows_loaded == 1

    result = validate_and_dedupe(conn)
    assert result.rows_in == 1
    assert result.rows_valid == 1
    assert result.rows_rejected_invalid == 0
    assert result.rows_rejected_collision == 0

    types = {
        row[0]: row[1]
        for row in conn.execute(f'DESCRIBE "{TABLE_VALID}"').fetchall()
    }
    assert "DATE" in types["action_date"].upper()
    assert "DECIMAL" in types["federal_action_obligation"].upper()

def test_validate_rejects_malformed_and_missing(tmp_path: Path) -> None:
    csv_path = write_projected_csv(
        tmp_path / "bad.csv",
        [
            blank_projected_row(
                contract_transaction_unique_key="BAD_MONEY",
                federal_action_obligation="not-a-number",
            ),
            blank_projected_row(
                contract_transaction_unique_key="",
                contract_award_unique_key="A2",
            ),
        ],
    )
    conn = connect_staging(tmp_path / "bad.duckdb")
    load_projected_csvs(conn, [csv_path])
    result = validate_and_dedupe(conn)
    assert result.rows_valid == 0
    assert result.rows_rejected_invalid == 2

    reasons = {
        row[0]
        for row in conn.execute(
            f'SELECT reject_reason FROM "{TABLE_REJECTS}"'
        ).fetchall()
    }
    assert any("malformed:federal_action_obligation" in r for r in reasons)
    assert any("missing_required:contract_transaction_unique_key" in r for r in reasons)

def test_exact_dup_collapse_across_inputs(tmp_path: Path) -> None:
    row = blank_projected_row(contract_transaction_unique_key="SHARED")
    a = write_projected_csv(tmp_path / "a.csv", [row])
    b = write_projected_csv(tmp_path / "b.csv", [row, blank_projected_row(
        contract_transaction_unique_key="OTHER",
        contract_award_unique_key="AWD_2",
    )])

    conn = connect_staging(tmp_path / "dup.duckdb")
    load = load_projected_csvs(conn, [a, b])
    assert load.rows_loaded == 3

    result = validate_and_dedupe(conn)
    assert result.rows_collapsed_dupes == 1
    assert result.rows_valid == 2
    assert result.rows_rejected_collision == 0

def test_identity_collision_rejects_all(tmp_path: Path) -> None:
    base = blank_projected_row(contract_transaction_unique_key="SAME")
    collided = blank_projected_row(
        contract_transaction_unique_key="SAME",
        transaction_description="different payload",
    )
    a = write_projected_csv(tmp_path / "c1.csv", [base])
    b = write_projected_csv(tmp_path / "c2.csv", [collided])

    conn = connect_staging(tmp_path / "collision.duckdb")
    load_projected_csvs(conn, [a, b])
    result = validate_and_dedupe(conn)
    assert result.rows_valid == 0
    assert result.rows_rejected_collision == 2
    collision_count = conn.execute(
        f"""
        SELECT COUNT(*) FROM "{TABLE_REJECTS}"
        WHERE reject_reason = 'identity_collision'
        """
    ).fetchone()
    assert collision_count is not None
    assert collision_count[0] == 2

def test_load_ignores_extra_header_columns(tmp_path: Path) -> None:
    """Extras beyond the projection allowlist are allowed at load."""

    path = tmp_path / "extra.csv"
    fieldnames = list(TRANSACTION_DOWNLOAD_COLUMNS) + ["extra_noise"]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        row = blank_projected_row()
        row["extra_noise"] = "ignore-me"
        writer.writerow(row)

    conn = connect_staging(tmp_path / "extra.duckdb")
    load = load_projected_csvs(conn, [path])
    assert load.rows_loaded == 1
    cols = {
        row[0]
        for row in conn.execute(f'DESCRIBE "{TABLE_RAW}"').fetchall()
    }
    assert "extra_noise" not in cols
