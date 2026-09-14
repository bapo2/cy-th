# tests/factories/projected_csv.py

"""Helpers for writing minimal projected USASpending CSVs in tests."""

# === Imports ===

from __future__ import annotations
import csv
from pathlib import Path
from typing import Mapping, Sequence

from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Row Builders ===

def blank_projected_row(**overrides: str) -> dict[str, str]:
    """Build one projected CSV row (all columns present; blanks default).

    Supplies a minimal valid identity + `action_date` so most overrides stay small.
    """

    row = {column: "" for column in TRANSACTION_DOWNLOAD_COLUMNS}
    row.update(
        {
            "contract_transaction_unique_key": "TXN_1",
            "contract_award_unique_key": "AWD_1",
            "action_date": "2025-01-15",
            "federal_action_obligation": "1.00",
            "transaction_number": "0",
        }
    )
    row.update(overrides)
    return row

def write_projected_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> Path:
    """Write `rows` as a projected-column CSV; returns `path`."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(TRANSACTION_DOWNLOAD_COLUMNS),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: row.get(column, "") for column in TRANSACTION_DOWNLOAD_COLUMNS}
            )
    return path
