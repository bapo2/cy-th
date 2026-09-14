# cy_th/ingest/types.py

"""Typed models for ingest jobs, shards, and download results."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


# === Enums ===

class JobStatus(StrEnum):
    """Control-plane status for one ingest job directory."""

    PLANNED = "planned"
    DOWNLOADING = "downloading"
    ACQUIRED = "acquired"
    MATERIALIZED = "materialized"


# === Windows / Shards ===

@dataclass(frozen=True, slots=True)
class DateWindow:
    """Inclusive `action_date` interval."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"DateWindow end {self.end.isoformat()} precedes start {self.start.isoformat()}"
            )

    @property
    def shard_id(self) -> str:
        """Deterministic shard identity (`YYYY-MM-DD_YYYY-MM-DD`)."""

        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DateWindow:
        return cls(
            start=date.fromisoformat(str(raw["start"])),
            end=date.fromisoformat(str(raw["end"])),
        )

@dataclass(frozen=True, slots=True)
class PlannedShard:
    """One planned download window plus the count used to accept it."""

    window: DateWindow
    planned_count: int

    def to_dict(self) -> dict[str, Any]:
        return {**self.window.to_dict(), "planned_count": self.planned_count}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlannedShard:
        return cls(
            window=DateWindow.from_dict(raw),
            planned_count=int(raw["planned_count"]),
        )

@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Outcome of extracting one projected CSV from a download zip."""

    row_count: int
    source_file_name: str | None
    bytes_written: int

@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary of one `ingest()` run."""

    job_id: str
    data_root: Path
    job_dir: Path
    from_date: date
    to_date: date
    shards: tuple[PlannedShard, ...]
    csv_paths: tuple[Path, ...]
    downloaded: int
    skipped_complete: int
    status: JobStatus
    run_id: str | None = None


# === Client Protocol ===

@runtime_checkable
class DownloadClient(Protocol):
    """Count + download projected prime transactions for one date window."""

    def count_transactions(self, window: DateWindow) -> int:
        """Return USASpending's transaction count for `window`."""
        ...

    def download_transactions(self, window: DateWindow, dest_csv: Path) -> DownloadResult:
        """Write a projected PrimeTransactions CSV to `dest_csv`."""
        ...
