# cy_th/query/dataset.py

"""Session-scoped access to the published procurement dataset."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Sequence, Self
import duckdb

from cy_th.query.aggregate import aggregate_activity
from cy_th.query.open import OpenDataset, open_published_dataset
from cy_th.query.resolve import resolve_awards
from cy_th.query.types import (
    ActivityWindow,
    AwardActivityRow,
    AwardFilters,
    GroupBy,
    RecipientActivityRow,
)


# === Dataset ===

@dataclass(slots=True)
class ProcurementDataset:
    """Read-only query session over one pinned published Parquet set.

    Wraps an `OpenDataset` from open time and adds session lifecycle (`close` / context manager). Resolves `CURRENT` once and keeps the pinned set stable (even if `CURRENT` changes on disk afterward).
    """

    _opened: OpenDataset
    _closed: bool = False

    @classmethod
    def open(cls, data_root: Path | str | None = None) -> Self:
        """Open the active published dataset under `data_root` (default `.data/`)."""

        return cls(_opened=open_published_dataset(data_root))

    @property
    def opened(self) -> OpenDataset:
        """Pinned dataset snapshot (paths + DuckDB connection)."""

        self._ensure_open()
        return self._opened

    @property
    def data_root(self) -> Path:
        return self._opened.data_root

    @property
    def run_id(self) -> str:
        return self._opened.run_id

    @property
    def set_path(self) -> Path:
        return self._opened.set_path

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Underlying DuckDB connection (views registered at open time)."""

        self._ensure_open()
        return self._opened.conn

    def resolve_awards(self, filters: AwardFilters | None = None) -> frozenset[str]:
        """Resolve qualifying Award IDs from projected topology filters."""

        self._ensure_open()
        return resolve_awards(self._opened.conn, filters)

    def aggregate_activity(
        self,
        award_ids: Sequence[str],
        window: ActivityWindow,
        *,
        group_by: GroupBy = GroupBy.AWARD,
        limit: int | None = None,
    ) -> list[AwardActivityRow] | list[RecipientActivityRow]:
        """Aggregate obligations for `award_ids` inside `window`."""

        self._ensure_open()
        return aggregate_activity(
            self._opened.conn,
            award_ids,
            window,
            group_by=group_by,
            limit=limit,
        )

    def close(self) -> None:
        """Close the DuckDB connection."""

        if not self._closed:
            self._opened.conn.close()
            self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ProcurementDataset is closed")
