# cy_th/query/errors.py

"""Errors raised when opening or querying the published dataset."""

# === Imports ===

from __future__ import annotations
from pathlib import Path


# === Base ===

class QueryError(RuntimeError):
    """Base class for procurement query runtime failures."""


# === Open / Dataset ===

class MissingCurrentError(QueryError):
    """Raised when `CURRENT` is missing or blank."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        super().__init__(f"CURRENT pointer missing or blank under {data_root}")

class InvalidRunIdError(QueryError):
    """Raised when `CURRENT` does not contain a valid run-ID."""

    def __init__(self, *, data_root: Path, run_id: str) -> None:
        self.data_root = data_root
        self.run_id = run_id
        super().__init__(f"invalid run-ID in CURRENT: {run_id!r} (under {data_root})")

class IncompleteDatasetError(QueryError):
    """Raised when the referenced set directory or required Parquet files are missing."""

    def __init__(self, *, run_id: str, set_path: Path, detail: str) -> None:
        self.run_id = run_id
        self.set_path = set_path
        self.detail = detail
        super().__init__(f"incomplete dataset set {run_id}: {detail} ({set_path})")

class UnreadableDatasetError(QueryError):
    """Raised when expected relations/columns cannot be read from the pinned set."""

    def __init__(self, *, run_id: str, detail: str) -> None:
        self.run_id = run_id
        self.detail = detail
        super().__init__(f"unreadable dataset set {run_id}: {detail}")
