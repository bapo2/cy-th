# cy_th/ingest/fake.py

"""Offline `DownloadClient` for tests (no network)."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import csv

from cy_th.ingest.types import DateWindow, DownloadResult
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Client ===

@dataclass
class FakeDownloadClient:
    """Scripted counts + CSV writer keyed by `DateWindow.shard_id` (else per-day density)."""

    counts: dict[str, int] = field(default_factory=dict)
    rows_per_day: int = 1
    csv_rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    count_calls: list[str] = field(default_factory=list)
    download_calls: list[str] = field(default_factory=list)

    def count_transactions(self, window: DateWindow) -> int:
        self.count_calls.append(window.shard_id)
        if window.shard_id in self.counts:
            return self.counts[window.shard_id]
        days = (window.end - window.start).days + 1
        return days * self.rows_per_day

    def download_transactions(self, window: DateWindow, dest_csv: Path) -> DownloadResult:
        self.download_calls.append(window.shard_id)
        rows = self.csv_rows.get(window.shard_id)
        if rows is None:
            if window.shard_id in self.counts:
                count = self.counts[window.shard_id]
            else:
                days = (window.end - window.start).days + 1
                count = days * self.rows_per_day
            rows = [_blank_row(f"{window.shard_id}-{i}") for i in range(count)]

        dest_csv.parent.mkdir(parents=True, exist_ok=True)
        with dest_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(TRANSACTION_DOWNLOAD_COLUMNS))
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in TRANSACTION_DOWNLOAD_COLUMNS})

        return DownloadResult(
            row_count=len(rows),
            source_file_name=f"fake_{window.shard_id}.zip",
            bytes_written=dest_csv.stat().st_size,
        )


# === Helpers ===

def _blank_row(txn_id: str) -> dict[str, str]:
    row = {col: "" for col in TRANSACTION_DOWNLOAD_COLUMNS}
    row["contract_transaction_unique_key"] = txn_id
    row["contract_award_unique_key"] = f"A-{txn_id}"
    row["action_date"] = "2025-01-01"
    return row
