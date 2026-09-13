# tests/cy_th/schema/test_projection.py

"""Tests for the USASpending transaction-download projection allowlist."""

# === Imports ===

import csv
from pathlib import Path

from cy_th.schema.projection import (
    COLUMN_PURPOSE,
    DEFERRED_DOWNLOAD_COLUMNS,
    TRANSACTION_DOWNLOAD_COLUMNS,
    ColumnPurpose,
)


# === Constants ===

def test_projection_and_purpose_maps_align() -> None:
    assert len(TRANSACTION_DOWNLOAD_COLUMNS) == len(set(TRANSACTION_DOWNLOAD_COLUMNS))
    assert set(TRANSACTION_DOWNLOAD_COLUMNS) == set(COLUMN_PURPOSE)
    assert "date_signed" not in TRANSACTION_DOWNLOAD_COLUMNS
    assert "period_of_performance_potential_end_date" not in TRANSACTION_DOWNLOAD_COLUMNS
    assert "period_of_performance_potential_end_date" in DEFERRED_DOWNLOAD_COLUMNS

def test_purpose_tags_cover_core_buckets() -> None:
    assert ColumnPurpose.ACTIVITY in COLUMN_PURPOSE["federal_action_obligation"]
    assert ColumnPurpose.AWARD_SNAPSHOT in COLUMN_PURPOSE["total_dollars_obligated"]
    assert ColumnPurpose.AWARD_TOPOLOGY in COLUMN_PURPOSE["recipient_uei"]
    assert ColumnPurpose.REF_DESCRIPTOR in COLUMN_PURPOSE["recipient_name"]


# === Real Extract ===

def test_cached_extract_header_matches_projection(prime_txn_csv_path: Path) -> None:
    with Path(prime_txn_csv_path).open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == list(TRANSACTION_DOWNLOAD_COLUMNS)

def test_real_rows_include_identity_and_money_fields(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    row = prime_txn_sample[0]
    for col in (
        "contract_transaction_unique_key",
        "contract_award_unique_key",
        "action_date",
        "federal_action_obligation",
        "total_dollars_obligated",
        "current_total_value_of_award",
        "potential_total_value_of_award",
        "recipient_zip_4_code",
        "prime_award_transaction_recipient_county_fips_code",
    ):
        assert col in row
