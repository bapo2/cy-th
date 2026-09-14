# cy_th/query/open.py

"""Open a pinned published dataset and register read-only DuckDB views."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Final
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.paths import is_run_id, read_current, refs_dir, resolve_data_root, set_dir
from cy_th.materialize.publish import AWARDS_PARQUET, TRANSACTIONS_PARQUET, _REF_PARQUET
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_CLASSIFICATIONS,
    TABLE_IDVS,
    TABLE_LOCATIONS,
    TABLE_OFFICES,
    TABLE_RECIPIENTS,
)
from cy_th.materialize.transactions import TABLE_TRANSACTIONS
from cy_th.query.errors import (
    IncompleteDatasetError,
    InvalidRunIdError,
    MissingCurrentError,
    UnreadableDatasetError,
)
from cy_th.schema.db_types import quote_ident


# === Constants ===

_PK_BY_VIEW: Final[dict[str, str]] = {
    TABLE_TRANSACTIONS: "transaction_id",
    TABLE_AWARDS: "award_id",
    TABLE_RECIPIENTS: "uei",
    TABLE_AGENCIES: "agency_id",
    TABLE_OFFICES: "office_id",
    TABLE_IDVS: "idv_id",
    TABLE_CLASSIFICATIONS: "classification_id",
    TABLE_LOCATIONS: "location_id",
}


# === Result ===

@dataclass(frozen=True, slots=True)
class OpenDataset:
    """Pinned published dataset ready for read-only queries."""

    data_root: Path
    run_id: str
    set_path: Path
    conn: duckdb.DuckDBPyConnection


# === Public API ===

def open_published_dataset(data_root: Path | str | None = None) -> OpenDataset:
    """Resolve `CURRENT`, validate the set layout, and register DuckDB views.

    #### Returns:
        Pinned dataset with an in-memory DuckDB connection over absolute Parquet paths
    """

    root = resolve_data_root(data_root)
    run_id = read_current(root)
    if run_id is None:
        raise MissingCurrentError(root)
    if not is_run_id(run_id):
        raise InvalidRunIdError(data_root=root, run_id=run_id)

    set_path = set_dir(root, run_id)
    if not set_path.is_dir():
        raise IncompleteDatasetError(
            run_id=run_id,
            set_path=set_path,
            detail="set directory missing",
        )

    views = _view_specs(set_path)
    _validate_required_files(run_id=run_id, set_path=set_path, views=views)

    conn = duckdb.connect()
    try:
        _register_views(conn, views)
        _probe_views(conn, run_id=run_id, views=views)
    except Exception:
        conn.close()
        raise

    return OpenDataset(data_root=root, run_id=run_id, set_path=set_path, conn=conn)


# === Layout ===

@dataclass(frozen=True, slots=True)
class _ViewSpec:
    """One DuckDB view over a canonical Parquet file."""

    name: str
    parquet_path: Path
    pk_column: str

def _view_specs(set_path: Path) -> tuple[_ViewSpec, ...]:
    """Build view specs for the canonical transaction, award, and ref tables."""

    ref_root = refs_dir(set_path)
    return (
        _ViewSpec(TABLE_TRANSACTIONS, set_path / TRANSACTIONS_PARQUET, "transaction_id"),
        _ViewSpec(TABLE_AWARDS, set_path / AWARDS_PARQUET, "award_id"),
        *(
            _ViewSpec(table, ref_root / filename, _PK_BY_VIEW[table])
            for table, filename in _REF_PARQUET.items()
        ),
    )

def _validate_required_files(
    *,
    run_id: str,
    set_path: Path,
    views: tuple[_ViewSpec, ...],
) -> None:
    """Ensure every required Parquet file exists before registering views."""

    for spec in views:
        if not spec.parquet_path.is_file():
            rel = spec.parquet_path.relative_to(set_path)
            raise IncompleteDatasetError(
                run_id=run_id,
                set_path=set_path,
                detail=f"missing required file: {rel.as_posix()}",
            )


# === DuckDB ===

def _register_views(conn: duckdb.DuckDBPyConnection, views: tuple[_ViewSpec, ...]) -> None:
    """Create read-only views over pinned absolute Parquet paths."""

    for spec in views:
        target = _parquet_sql_literal(spec.parquet_path)
        qname = quote_ident(spec.name)
        conn.execute(
            f"CREATE OR REPLACE VIEW {qname} AS "
            f"SELECT * FROM read_parquet('{target}')"
        )

def _probe_views(
    conn: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    views: tuple[_ViewSpec, ...],
) -> None:
    """Verify each view is readable and exposes its expected primary-key column."""

    for spec in views:
        qname = quote_ident(spec.name)
        try:
            columns = {
                str(row[0])
                for row in conn.execute(f"DESCRIBE SELECT * FROM {qname}").fetchall()
            }
        except duckdb.Error as exc:
            raise UnreadableDatasetError(
                run_id=run_id,
                detail=f"cannot describe view {spec.name}: {exc}",
            ) from exc

        if spec.pk_column not in columns:
            raise UnreadableDatasetError(
                run_id=run_id,
                detail=(
                    f"view {spec.name} missing expected column {spec.pk_column!r}"
                ),
            )

        try:
            conn.execute(f"SELECT 1 FROM {qname} LIMIT 0")
        except duckdb.Error as exc:
            raise UnreadableDatasetError(
                run_id=run_id,
                detail=f"cannot read view {spec.name}: {exc}",
            ) from exc


# === Helpers ===

def _parquet_sql_literal(path: Path) -> str:
    """Escape an absolute Parquet path for embedding in DuckDB SQL."""

    return path.resolve().as_posix().replace("'", "''")
