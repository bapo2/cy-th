# cy_th/materialize/load.py

"""Load projected USASpending CSVs into a DuckDB staging database.

Validates headers (`TRANSACTION_DOWNLOAD_COLUMNS ⊆ header`, no duplicate names), then unions N ≥ 1 inputs into `staging_raw` as all-VARCHAR projected columns + source provenance fields.
"""

# === Imports ===

from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence
import duckdb

from cy_th.schema.db_types import quote_ident
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Constants ===

TABLE_RAW: Final[str] = "staging_raw"
"""Union of projected CSV rows (all VARCHAR) before cast/validate."""

_META_COLS: Final[tuple[str, ...]] = (
    "_source_path",
    "_input_index",
    "_load_seq",
)


# === Results ===

@dataclass(frozen=True, slots=True)
class LoadResult:
    """Summary of a multi-CSV load into `staging_raw`."""

    input_files: int
    rows_loaded: int


# === Header Checks ===

def read_csv_header(path: Path) -> list[str]:
    """Read the first CSV row as column names."""

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{path}: empty file (no header)") from exc
    return header

def assert_projected_header(path: Path, header: Sequence[str]) -> None:
    """Require unique names and `TRANSACTION_DOWNLOAD_COLUMNS ⊆ header`.
    
    Extra columns are allowed (but ignored at load) while duplicate names fail.
    """

    if len(header) != len(set(header)):
        dupes = sorted({name for name in header if header.count(name) > 1})
        raise ValueError(f"{path}: duplicate header names: {dupes}")

    present = set(header)
    missing = [c for c in TRANSACTION_DOWNLOAD_COLUMNS if c not in present]
    if missing:
        raise ValueError(
            f"{path}: missing required projected columns ({len(missing)}): "
            f"{missing[:8]}{'…' if len(missing) > 8 else ''}"
        )


# === Connection ===

def connect_staging(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB file (parent dirs created as-needed)."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


# === Load ===

def load_projected_csvs(
    conn: duckdb.DuckDBPyConnection,
    paths: Sequence[Path | str],
) -> LoadResult:
    """Union projected columns from `paths` into `staging_raw`.

    Zero inputs, missing file, bad/duplicate/incomplete header raise `ValueError`.
    """

    if not paths:
        raise ValueError("at least one CSV path is required")

    resolved: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"CSV not found: {path}")
        header = read_csv_header(path)
        assert_projected_header(path, header)
        resolved.append(path.resolve())

    projected = ", ".join(quote_ident(c) for c in TRANSACTION_DOWNLOAD_COLUMNS)
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident(TABLE_RAW)}")

    # Create empty shell w/ projected VARCHAR cols + provenance
    col_ddl = ", ".join(
        f"{quote_ident(c)} VARCHAR" for c in TRANSACTION_DOWNLOAD_COLUMNS
    )
    meta_ddl = (
        f"{quote_ident('_source_path')} VARCHAR NOT NULL, "
        f"{quote_ident('_input_index')} INTEGER NOT NULL, "
        f"{quote_ident('_load_seq')} BIGINT NOT NULL"
    )
    conn.execute(
        f"CREATE TABLE {quote_ident(TABLE_RAW)} ({col_ddl}, {meta_ddl})"
    )

    seq = 0
    for input_index, path in enumerate(resolved):
        conn.execute(
            f"""
            INSERT INTO {quote_ident(TABLE_RAW)}
            SELECT
              {projected},
              ? AS {quote_ident('_source_path')},
              ? AS {quote_ident('_input_index')},
              (? + ROW_NUMBER() OVER ())::BIGINT AS {quote_ident('_load_seq')}
            FROM read_csv(
              ?,
              header := true,
              all_varchar := true,
              parallel := false
            )
            """,  # ↑ `parallel := false` keeps insert order stable for `_load_seq` assignment
            [str(path), input_index, seq, str(path)],
        )
        added = conn.execute(
            f"""
            SELECT COUNT(*) FROM {quote_ident(TABLE_RAW)}
            WHERE {quote_ident('_input_index')} = ?
            """,
            [input_index],
        ).fetchone()
        assert added is not None
        seq += int(added[0])

    total = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(TABLE_RAW)}"
    ).fetchone()
    assert total is not None
    return LoadResult(input_files=len(resolved), rows_loaded=int(total[0]))
