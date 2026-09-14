# cy_th/materialize/validate.py

"""Cast, reject, content-hash, and dedupe `staging_raw` into `staging_valid`.

#### Rules:
    - Blank → NULL for all projected fields
    - Blank required ID / `action_date` → reject (`missing_required:*`)
    - Non-blank malformed money / date → reject (`malformed:*`)
    - Projected payload dups (content hash in `transaction_id`) → keep one
    - Same ID, disagreeing hash → reject all (`identity_collision`)
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from typing import Final
import duckdb

from cy_th.materialize.load import TABLE_RAW
from cy_th.schema.db_types import blank_as_null_expr, cast_expr, quote_ident
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS
from cy_th.schema.types import DATE, MONEY, STRING, TypeSpec


# === Constants ===

TABLE_REJECTS: Final[str] = "rejects"
"""Rows that failed cast/required checks or lost an identity collision."""

TABLE_VALID: Final[str] = "staging_valid"
"""Deduped, typed projected rows ready for `TransactionFact` / ref / Award reduce."""

TXN_ID_COL: Final[str] = "contract_transaction_unique_key"
CONTENT_HASH_COL: Final[str] = "_content_hash"

_REQUIRED_COLS: Final[tuple[str, ...]] = (
    "contract_transaction_unique_key",
    "contract_award_unique_key",
    "action_date",
)

_DATE_COLS: Final[tuple[str, ...]] = (
    "action_date",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
)

_MONEY_COLS: Final[tuple[str, ...]] = (
    "federal_action_obligation",
    "total_dollars_obligated",
    "current_total_value_of_award",
    "potential_total_value_of_award",
)

_SQL_LIST_SEP: Final[str] = ",\n  "  # 2-space indent to match existing SQL ↓
"""Join separator for multi-line generated SQL argument / SELECT lists."""


# === Results ===

@dataclass(frozen=True, slots=True)
class ValidateResult:
    """Summary of cast / reject / dedupe over `staging_raw`."""

    rows_in: int
    rows_rejected_invalid: int
    """Missing required or malformed money/date."""

    rows_rejected_collision: int
    """Rows discarded because `transaction_id` had disagreeing content hashes."""

    rows_collapsed_dupes: int
    """Exact-payload duplicates removed (kept one per ID)."""

    rows_valid: int
    """Rows remaining in `staging_valid`."""


# === Type Binding ===

def projected_type(column: str) -> TypeSpec:
    """Logical type for a projected download column (string unless date/money)."""

    if column in _DATE_COLS:
        return DATE
    if column in _MONEY_COLS:
        return MONEY
    return STRING


# === Validate + Dedupe ===

def validate_and_dedupe(conn: duckdb.DuckDBPyConnection) -> ValidateResult:
    """Build `rejects` + `staging_valid` from `staging_raw`.

    Raises `ValueError` if `staging_raw` is missing.
    """

    exists = conn.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = ?
        """,
        [TABLE_RAW],
    ).fetchone()
    if exists is None or int(exists[0]) == 0:
        raise ValueError(f"{TABLE_RAW} does not exist; load CSVs first")

    rows_in_row = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(TABLE_RAW)}"
    ).fetchone()
    assert rows_in_row is not None
    rows_in = int(rows_in_row[0])

    norm_select = _normalized_select_sql()
    reason_sql = _reject_reason_sql()
    hash_sql = _content_hash_sql()
    typed_select = _typed_select_sql(alias="n")

    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_staging_normalized')}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_staging_assessed')}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident(TABLE_REJECTS)}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident(TABLE_VALID)}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_collision_ids')}")

    # Blank-norm'd VARCHAR projection + provenance
    conn.execute(
        f"""
        CREATE TABLE {quote_ident('_staging_normalized')} AS
        SELECT
          {norm_select},
          {quote_ident('_source_path')},
          {quote_ident('_input_index')},
          {quote_ident('_load_seq')}
        FROM {quote_ident(TABLE_RAW)}
        """
    )

    # Attach reject reasons + content hash
    conn.execute(
        f"""
        CREATE TABLE {quote_ident('_staging_assessed')} AS
        SELECT
          n.*,
          {reason_sql} AS {quote_ident('_reject_reason')},
          {hash_sql} AS {quote_ident(CONTENT_HASH_COL)}
        FROM {quote_ident('_staging_normalized')} AS n
        """
    )

    # Send invalid rows to rejects
    conn.execute(
        f"""
        CREATE TABLE {quote_ident(TABLE_REJECTS)} AS
        SELECT
          {quote_ident('_source_path')},
          {quote_ident('_input_index')},
          {quote_ident('_load_seq')},
          {quote_ident(TXN_ID_COL)},
          {quote_ident('_reject_reason')} AS {quote_ident('reject_reason')},
          {", ".join(quote_ident(c) for c in TRANSACTION_DOWNLOAD_COLUMNS)}
        FROM {quote_ident('_staging_assessed')}
        WHERE {quote_ident('_reject_reason')} IS NOT NULL
        """
    )

    invalid_count_row = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(TABLE_REJECTS)}"
    ).fetchone()
    assert invalid_count_row is not None
    rows_rejected_invalid = int(invalid_count_row[0])

    # Collision IDs among cast-OK rows
    conn.execute(
        f"""
        CREATE TABLE {quote_ident('_collision_ids')} AS
        SELECT {quote_ident(TXN_ID_COL)} AS {quote_ident('txn_id')}
        FROM {quote_ident('_staging_assessed')}
        WHERE {quote_ident('_reject_reason')} IS NULL
        GROUP BY {quote_ident(TXN_ID_COL)}
        HAVING COUNT(DISTINCT {quote_ident(CONTENT_HASH_COL)}) > 1
        """
    )

    # Send collision rows to rejects
    conn.execute(
        f"""
        INSERT INTO {quote_ident(TABLE_REJECTS)}
        SELECT
          a.{quote_ident('_source_path')},
          a.{quote_ident('_input_index')},
          a.{quote_ident('_load_seq')},
          a.{quote_ident(TXN_ID_COL)},
          'identity_collision' AS {quote_ident('reject_reason')},
          {", ".join(f"a.{quote_ident(c)}" for c in TRANSACTION_DOWNLOAD_COLUMNS)}
        FROM {quote_ident('_staging_assessed')} AS a
        INNER JOIN {quote_ident('_collision_ids')} AS c
          ON a.{quote_ident(TXN_ID_COL)} = c.{quote_ident('txn_id')}
        WHERE a.{quote_ident('_reject_reason')} IS NULL
        """
    )

    # Count collision rows in rejects
    collision_count_row = conn.execute(
        f"""
        SELECT COUNT(*) FROM {quote_ident(TABLE_REJECTS)}
        WHERE {quote_ident('reject_reason')} = 'identity_collision'
        """
    ).fetchone()
    assert collision_count_row is not None
    rows_rejected_collision = int(collision_count_row[0])

    # Duplicate collapse (one row per ID among non-colliding cast-OK rows)
    conn.execute(
        f"""
        CREATE TABLE {quote_ident(TABLE_VALID)} AS
        SELECT
          {typed_select},
          n.{quote_ident(CONTENT_HASH_COL)} AS {quote_ident(CONTENT_HASH_COL)},
          n.{quote_ident('_source_path')} AS {quote_ident('_source_path')},
          n.{quote_ident('_input_index')} AS {quote_ident('_input_index')},
          n.{quote_ident('_load_seq')} AS {quote_ident('_load_seq')}
        FROM (
          SELECT
            a.*,
            ROW_NUMBER() OVER (
              PARTITION BY a.{quote_ident(TXN_ID_COL)}
              ORDER BY a.{quote_ident('_load_seq')} ASC
            ) AS {quote_ident('_rn')}
          FROM {quote_ident('_staging_assessed')} AS a
          LEFT JOIN {quote_ident('_collision_ids')} AS c
            ON a.{quote_ident(TXN_ID_COL)} = c.{quote_ident('txn_id')}
          WHERE a.{quote_ident('_reject_reason')} IS NULL
            AND c.{quote_ident('txn_id')} IS NULL
        ) AS n
        WHERE n.{quote_ident('_rn')} = 1
        """
    )

    # Count valid rows in `staging_valid`
    valid_count_row = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(TABLE_VALID)}"
    ).fetchone()
    assert valid_count_row is not None
    rows_valid = int(valid_count_row[0])

    # Cast-OK non-collision rows before collapse = valid + collapsed dupes
    ok_non_collision_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {quote_ident('_staging_assessed')} AS a
        LEFT JOIN {quote_ident('_collision_ids')} AS c
          ON a.{quote_ident(TXN_ID_COL)} = c.{quote_ident('txn_id')}
        WHERE a.{quote_ident('_reject_reason')} IS NULL
          AND c.{quote_ident('txn_id')} IS NULL
        """
    ).fetchone()
    assert ok_non_collision_row is not None
    rows_collapsed_dupes = int(ok_non_collision_row[0]) - rows_valid

    # Drop scratch tables and keep raw/rejects/valid for downstream
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_staging_normalized')}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_staging_assessed')}")
    conn.execute(f"DROP TABLE IF EXISTS {quote_ident('_collision_ids')}")

    return ValidateResult(
        rows_in=rows_in,
        rows_rejected_invalid=rows_rejected_invalid,
        rows_rejected_collision=rows_rejected_collision,
        rows_collapsed_dupes=rows_collapsed_dupes,
        rows_valid=rows_valid,
    )


# === SQL Builders ===

def _normalized_select_sql() -> str:
    """Blank-norm'd VARCHAR expressions for every projected column."""

    parts: list[str] = []
    for col in TRANSACTION_DOWNLOAD_COLUMNS:
        ref = quote_ident(col)
        parts.append(f"{blank_as_null_expr(ref)} AS {ref}")
    return _SQL_LIST_SEP.join(parts)

def _reject_reason_sql() -> str:
    """Concatenated reject reasons, or NULL when the row is cast-OK."""

    pieces: list[str] = []

    for col in _REQUIRED_COLS:
        ref = quote_ident(col)
        pieces.append(
            f"CASE WHEN {ref} IS NULL THEN 'missing_required:{col}' END"
        )

    for col in _DATE_COLS:
        raw = quote_ident(col)
        # Norm'd col already blank → NULL; malformed = non-null text that won't cast
        pieces.append(
            f"CASE WHEN {raw} IS NOT NULL AND "
            f"TRY_CAST({raw} AS DATE) IS NULL THEN 'malformed:{col}' END"
        )

    for col in _MONEY_COLS:
        raw = quote_ident(col)
        pieces.append(
            f"CASE WHEN {raw} IS NOT NULL AND "
            f"TRY_CAST({raw} AS DECIMAL(20, 2)) IS NULL THEN 'malformed:{col}' END"
        )

    joined = _SQL_LIST_SEP.join(pieces)
    return f"NULLIF(concat_ws('; ', {joined}), '')"

def _content_hash_sql() -> str:
    """SHA-256 over blank-norm'd projected payload (ordered cols)."""

    coalesced = _SQL_LIST_SEP.join(
        f"coalesce({quote_ident(c)}, '')" for c in TRANSACTION_DOWNLOAD_COLUMNS
    )
    return f"sha256(concat_ws(chr(31), {coalesced}))"  # chr(31) is unit separator

def _typed_select_sql(*, alias: str) -> str:
    """Cast normalized VARCHAR columns to DuckDB physical types."""

    parts: list[str] = []
    for col in TRANSACTION_DOWNLOAD_COLUMNS:
        ref = f"{quote_ident(alias)}.{quote_ident(col)}"
        spec = projected_type(col)
        parts.append(f"{cast_expr(ref, spec)} AS {quote_ident(col)}")
    return _SQL_LIST_SEP.join(parts)
