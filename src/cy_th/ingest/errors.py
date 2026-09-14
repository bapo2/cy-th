# cy_th/ingest/errors.py

"""Errors raised by USASpending acquisition / ingest."""

# === Imports ===

from __future__ import annotations
from datetime import date


# === Base ===

class IngestError(RuntimeError):
    """Base class for ingest / acquisition failures."""


# === Request ===

class InvalidIngestRequestError(IngestError):
    """Raised for invalid `--from` / `--to` or job inputs."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

class ShardTooLargeError(IngestError):
    """Raised when a single `action_date` still exceeds the download cap."""

    def __init__(self, *, day: date, count: int, cap: int) -> None:
        self.day = day
        self.count = count
        self.cap = cap
        super().__init__(
            f"action_date {day.isoformat()} has {count} transactions; exceeds download cap {cap} and cannot be subdivided"
        )


# === Transport ===

class UsaSpendingApiError(IngestError):
    """Raised when a USASpending download/count request fails."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

class TransientUsaSpendingError(UsaSpendingApiError):
    """Raised after retries for gateway timeouts / transient upstream failures.

    Large `action_date` windows often 504 on `/download/count/`; the planner treats this as "too large to count" and bisects.
    """

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)

class DownloadJobFailedError(UsaSpendingApiError):
    """Raised when USASpending marks an async download job as failed."""

    def __init__(self, detail: str, *, file_name: str | None = None) -> None:
        self.file_name = file_name
        super().__init__(detail)
