# cy_th/query/dataset.py

"""Session-scoped access to the published procurement dataset."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import secrets
from types import TracebackType
from typing import Collection, Literal, Self, overload
import duckdb

from cy_th.query.aggregate import aggregate_activity
from cy_th.query.errors import StaleSelectionError
from cy_th.query.open import OpenDataset, open_published_dataset
from cy_th.query.resolve import resolve_awards, select_awards, selection_award_ids
from cy_th.query.types import (
    ActivityWindow,
    AwardActivityRow,
    AwardFilters,
    AwardSelection,
    GroupBy,
    RecipientActivityRow,
)


# === Dataset ===

@dataclass(slots=True)
class ProcurementDataset:
    """Read-only query session over one pinned published Parquet set.

    Wraps an `OpenDataset` from open time and adds session lifecycle (`close` / context manager). Resolves `CURRENT` once and keeps the pinned set stable (even if `CURRENT` changes on disk afterward).

    `AwardSelection` values produced by this instance are bound to its `session_id` and rejected after `close()` or when used on another session.
    """

    pinned: OpenDataset
    _closed: bool = False
    _selection_seq: int = field(default=0, init=False, repr=False)
    _session_id: str = field(
        default_factory=lambda: secrets.token_hex(8),
        init=False,
        repr=False,
    )

    @classmethod
    def open(cls, data_root: Path | str | None = None) -> Self:
        """Open the active published dataset under `data_root` (default `.data/`)."""

        return cls(pinned=open_published_dataset(data_root))

    @property
    def session_id(self) -> str:
        """Opaque ID for this open session (selections must match it)."""

        return self._session_id

    @property
    def opened(self) -> OpenDataset:
        """Pinned dataset snapshot (paths + DuckDB connection)."""

        self._ensure_open()
        return self.pinned

    @property
    def data_root(self) -> Path:
        return self.pinned.data_root

    @property
    def run_id(self) -> str:
        return self.pinned.run_id

    @property
    def set_path(self) -> Path:
        return self.pinned.set_path

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Underlying DuckDB connection (views registered at open time)."""

        self._ensure_open()
        return self.pinned.conn

    def resolve_awards(self, filters: AwardFilters | None = None) -> AwardSelection:
        """Resolve qualifying Awards into a session-scoped DuckDB selection."""

        self._ensure_open()
        return resolve_awards(
            self.pinned.conn,
            filters,
            relation_name=self._new_selection_name(),
            session_id=self._session_id,
        )

    def select_awards(self, award_ids: Collection[str]) -> AwardSelection:
        """Build an `AwardSelection` from explicit Award IDs (tests / semantic handoff)."""

        self._ensure_open()
        return select_awards(
            self.pinned.conn,
            award_ids,
            relation_name=self._new_selection_name(),
            session_id=self._session_id,
        )

    def award_ids(self, selection: AwardSelection) -> frozenset[str]:
        """Materialize a selection's Award IDs into Python (tests / debug)."""

        self._require_selection(selection)
        return selection_award_ids(self.pinned.conn, selection)

    @overload
    def aggregate_activity(  # Overload for `AwardActivityRow` to make type-checker happy
        self,
        selection: AwardSelection,
        window: ActivityWindow,
        *,
        group_by: Literal[GroupBy.AWARD] = GroupBy.AWARD,
        limit: int | None = None,
    ) -> list[AwardActivityRow]: ...

    @overload
    def aggregate_activity(  # Overload for `RecipientActivityRow` to make type-checker happy
        self,
        selection: AwardSelection,
        window: ActivityWindow,
        *,
        group_by: Literal[GroupBy.RECIPIENT],
        limit: int | None = None,
    ) -> list[RecipientActivityRow]: ...

    def aggregate_activity(
        self,
        selection: AwardSelection,
        window: ActivityWindow,
        *,
        group_by: GroupBy = GroupBy.AWARD,
        limit: int | None = None,
    ) -> list[AwardActivityRow] | list[RecipientActivityRow]:
        """Aggregate obligations for a resolved/selected Award set inside `window`."""

        self._require_selection(selection)
        return aggregate_activity(
            self.pinned.conn,
            selection,
            window,
            group_by=group_by,
            limit=limit,
        )

    def close(self) -> None:
        """Close the DuckDB connection and invalidate this session's selections."""

        if not self._closed:
            self.pinned.conn.close()
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

    def _new_selection_name(self) -> str:
        self._selection_seq += 1
        return f"resolved_awards_{self._selection_seq}"

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ProcurementDataset is closed")

    def _require_selection(self, selection: AwardSelection) -> None:
        """Reject selections from other sessions or after this session closed."""

        if self._closed:
            raise StaleSelectionError(detail="query session is closed")
        if selection.session_id != self._session_id:
            raise StaleSelectionError(
                detail=(
                    "selection belongs to a different query session "
                    f"(selection={selection.session_id!r}, session={self._session_id!r})"
                )
            )
