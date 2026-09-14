# tests/cy_th/ingest/test_client_extract.py

"""Projected-CSV extract from a download zip (no network)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import csv
import io
import zipfile

from cy_th.ingest.client import _extract_prime_csv
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Extract ===

def test_extract_prime_transactions_member(tmp_path: Path) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(TRANSACTION_DOWNLOAD_COLUMNS))
    writer.writeheader()
    writer.writerow(
        {col: "" for col in TRANSACTION_DOWNLOAD_COLUMNS}
        | {
            "contract_transaction_unique_key": "T1",
            "contract_award_unique_key": "A1",
            "action_date": "2025-01-01",
        }
    )
    zip_path = tmp_path / "dl.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ignored.csv", "nope")
        zf.writestr("FY2025_Contracts_PrimeTransactions_v2.csv", buf.getvalue())

    dest = tmp_path / "out.csv"
    rows = _extract_prime_csv(zip_path, dest)
    assert rows == 1
    assert dest.is_file()
