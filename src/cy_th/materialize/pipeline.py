# cy_th/materialize/pipeline.py

"""End-to-end materialization pipeline (CSV → staging DuckDB → Parquet set + `CURRENT`)."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from cy_th.materialize.awards import materialize_awards
from cy_th.materialize.load import LoadResult, connect_staging, load_projected_csvs
from cy_th.materialize.paths import (
    is_run_id,
    new_run_id,
    resolve_data_root,
    staging_db_path,
    staging_dir,
)
from cy_th.materialize.publish import PublishResult, publish_set
from cy_th.materialize.references import RefMaterializeResult, materialize_references
from cy_th.materialize.transactions import materialize_transactions
from cy_th.materialize.validate import ValidateResult, validate_and_dedupe


# === Results ===

@dataclass(frozen=True, slots=True)
class MaterializeResult:
    """Summary of a full materialize run."""

    run_id: str
    data_root: Path
    load: LoadResult
    validate: ValidateResult
    transactions: int
    refs: RefMaterializeResult
    awards: int
    publish: PublishResult
    staging_path: Path
    staging_kept: bool


# === Pipeline ===

def materialize(
    csv_paths: Sequence[Path | str],
    *,
    out: Path | str | None = None,
    allow_rejects: bool = False,
    keep_staging: bool = False,
    run_id: str | None = None,
) -> MaterializeResult:
    """Materialize projected CSVs into a versioned Parquet set under `out`.

    #### Args:
        - `csv_paths`: One or more projected USASpending CSVs (`N >= 1`)
        - `out`: Data root (default `.data/`)
        - `allow_rejects`: If true, flip `CURRENT` even when rejects exist
        - `keep_staging`: If true, retain `.staging/<run-id>.duckdb`
        - `run_id`: Optional deterministic run-ID (for tests); else generated

    #### Raises:
        - `ValueError`: Bad inputs / run-ID / immutable set collision
        - `IntegrityError`: PK/FK checks failed (no set written)
    """

    if not csv_paths:
        raise ValueError("at least one CSV path is required")

    data_root = resolve_data_root(out)
    rid = run_id if run_id is not None else new_run_id()
    if not is_run_id(rid):
        raise ValueError(f"invalid run_id: {rid!r}")

    staging_dir(data_root).mkdir(parents=True, exist_ok=True)
    db_path = staging_db_path(data_root, rid)

    conn = connect_staging(db_path)
    staging_kept = keep_staging
    try:
        load = load_projected_csvs(conn, csv_paths)
        validate = validate_and_dedupe(conn)
        n_txn = materialize_transactions(conn)
        refs = materialize_references(conn)
        n_awards = materialize_awards(conn)
        published = publish_set(
            conn,
            data_root=data_root,
            run_id=rid,
            allow_rejects=allow_rejects,
        )
        return MaterializeResult(
            run_id=rid,
            data_root=data_root,
            load=load,
            validate=validate,
            transactions=n_txn,
            refs=refs,
            awards=n_awards,
            publish=published,
            staging_path=db_path,
            staging_kept=staging_kept,
        )
    finally:
        conn.close()
        if not staging_kept:
            _remove_staging(db_path)

def _remove_staging(db_path: Path) -> None:
    """Best-effort delete of the staging DuckDB file (+ WAL sidecars)."""

    for path in (
        db_path,
        Path(str(db_path) + ".wal"),
        Path(str(db_path) + ".tmp"),
    ):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
