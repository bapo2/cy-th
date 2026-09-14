# cy_th/materialize/publish.py

"""Write versioned Parquet sets, run integrity checks, and flip `CURRENT`."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Final, Sequence
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.paths import (
    refs_dir,
    set_dir,
    sets_dir,
    tmp_set_dir,
    write_current_atomic,
)
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_CLASSIFICATIONS,
    TABLE_IDVS,
    TABLE_LOCATIONS,
    TABLE_OFFICES,
    TABLE_RECIPIENTS,
)
from cy_th.materialize.transactions import TABLE_TRANSACTIONS
from cy_th.materialize.validate import TABLE_REJECTS
from cy_th.schema.db_types import quote_ident


# === Constants ===

TRANSACTIONS_PARQUET: Final[str] = "transactions.parquet"
AWARDS_PARQUET: Final[str] = "awards.parquet"
REJECTS_PARQUET: Final[str] = "rejects.parquet"

_REF_PARQUET: Final[dict[str, str]] = {
    TABLE_RECIPIENTS: "recipients.parquet",
    TABLE_AGENCIES: "agencies.parquet",
    TABLE_OFFICES: "offices.parquet",
    TABLE_IDVS: "idvs.parquet",
    TABLE_CLASSIFICATIONS: "classifications.parquet",
    TABLE_LOCATIONS: "locations.parquet",
}

_PK_CHECKS: Final[tuple[tuple[str, str], ...]] = (
    (TABLE_TRANSACTIONS, "transaction_id"),
    (TABLE_AWARDS, "award_id"),
    (TABLE_RECIPIENTS, "uei"),
    (TABLE_AGENCIES, "agency_id"),
    (TABLE_OFFICES, "office_id"),
    (TABLE_IDVS, "idv_id"),
    (TABLE_CLASSIFICATIONS, "classification_id"),
    (TABLE_LOCATIONS, "location_id"),
)

_AWARD_FK_CHECKS: Final[tuple[tuple[str, str, str], ...]] = (
    ("recipient_id", TABLE_RECIPIENTS, "uei"),
    ("awarding_agency_id", TABLE_AGENCIES, "agency_id"),
    ("awarding_sub_agency_id", TABLE_AGENCIES, "agency_id"),
    ("awarding_office_id", TABLE_OFFICES, "office_id"),
    ("funding_agency_id", TABLE_AGENCIES, "agency_id"),
    ("funding_sub_agency_id", TABLE_AGENCIES, "agency_id"),
    ("funding_office_id", TABLE_OFFICES, "office_id"),
    ("parent_idv_id", TABLE_IDVS, "idv_id"),
    ("naics_id", TABLE_CLASSIFICATIONS, "classification_id"),
    ("psc_id", TABLE_CLASSIFICATIONS, "classification_id"),
    ("recipient_location_id", TABLE_LOCATIONS, "location_id"),
    ("place_of_performance_id", TABLE_LOCATIONS, "location_id"),
)


# === Results / Errors ===

@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """One failed integrity check."""

    check: str
    count: int
    detail: str = ""

@dataclass(frozen=True, slots=True)
class IntegrityResult:
    """Outcome of PK/FK invariant checks over staging canonical tables."""

    ok: bool
    issues: tuple[IntegrityIssue, ...]

@dataclass(frozen=True, slots=True)
class PublishResult:
    """On-disk publish outcome for one run-ID."""

    run_id: str
    set_path: Path
    published: bool
    """Whether `CURRENT` was flipped to this run-ID."""

    wrote_rejects: bool
    reject_count: int

class IntegrityError(RuntimeError):
    """Raised when canonical tables fail PK/FK integrity checks."""

    def __init__(self, result: IntegrityResult) -> None:
        self.result = result
        parts = [
            f"{issue.check}={issue.count}" + (f" ({issue.detail})" if issue.detail else "")
            for issue in result.issues
        ]
        super().__init__("integrity checks failed: " + "; ".join(parts))


# === Integrity ===

def check_integrity(conn: duckdb.DuckDBPyConnection) -> IntegrityResult:
    """Validate PK uniqueness and locked FK relationships in staging tables."""

    issues: list[IntegrityIssue] = []

    # Primary key checks
    for table, pk in _PK_CHECKS:
        dup = _scalar(
            conn,
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT {quote_ident(pk)})
            FROM {quote_ident(table)}
            """,
        )
        if dup:
            issues.append(  # Flag integrity issue if duplicate PK found
                IntegrityIssue(
                    check=f"pk:{table}.{pk}",
                    count=dup,
                    detail="duplicate primary keys",
                )
            )
        nulls = _scalar(
            conn,
            f"""
            SELECT COUNT(*) FROM {quote_ident(table)}
            WHERE {quote_ident(pk)} IS NULL
            """,
        )
        if nulls:
            issues.append(  # Flag integrity issue if null PK found
                IntegrityIssue(
                    check=f"pk_null:{table}.{pk}",
                    count=nulls,
                    detail="null primary keys",
                )
            )

    # `TransactionFact.award_id` → `AwardRecord`
    missing_awards = _scalar(
        conn,
        f"""
        SELECT COUNT(*) FROM {quote_ident(TABLE_TRANSACTIONS)} t
        WHERE NOT EXISTS (
          SELECT 1 FROM {quote_ident(TABLE_AWARDS)} a
          WHERE a.{quote_ident('award_id')} = t.{quote_ident('award_id')}
        )
        """,
    )
    if missing_awards:
        issues.append(
            IntegrityIssue(
                check="fk:transaction_fact.award_id",
                count=missing_awards,
                detail="award_id missing from award_record",
            )
        )

    # `AwardRecord` foreign key checks
    for fk, ref_table, pk in _AWARD_FK_CHECKS:
        missing = _scalar(
            conn,
            f"""
            SELECT COUNT(*) FROM {quote_ident(TABLE_AWARDS)} a
            WHERE a.{quote_ident(fk)} IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM {quote_ident(ref_table)} r
                WHERE r.{quote_ident(pk)} = a.{quote_ident(fk)}
              )
            """,
        )
        if missing:
            issues.append(
                IntegrityIssue(
                    check=f"fk:award_record.{fk}",
                    count=missing,
                    detail=f"missing {ref_table}.{pk}",
                )
            )

    for col in ("projection_transaction_id", "snapshot_transaction_id"):
        missing = _scalar(
            conn,
            f"""
            SELECT COUNT(*) FROM {quote_ident(TABLE_AWARDS)} a
            WHERE a.{quote_ident(col)} IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM {quote_ident(TABLE_TRANSACTIONS)} t
                WHERE t.{quote_ident('transaction_id')} = a.{quote_ident(col)}
              )
            """,
        )
        if missing:
            issues.append(
                IntegrityIssue(
                    check=f"fk:award_record.{col}",
                    count=missing,
                    detail="missing transaction_fact.transaction_id",
                )
            )

    return IntegrityResult(ok=not issues, issues=tuple(issues))


# === Parquet Write ===

def write_parquet_set(
    conn: duckdb.DuckDBPyConnection,
    data_root: Path,
    run_id: str,
) -> Path:
    """Write canonical tables under `sets/<run-id>/` (immutable; must not already exist).

    Assembles files under `.tmp-<run-id>/`, then renames into `sets/<run-id>/` only after every COPY succeeds so a mid-write failure never leaves a partial immutable set.

    #### Returns:
        Path to the new set directory
    """

    out = set_dir(data_root, run_id)
    if out.exists():
        raise ValueError(f"set directory already exists (immutable): {out}")

    tmp = tmp_set_dir(data_root, run_id)
    if tmp.exists():
        shutil.rmtree(tmp)

    try:
        tmp.mkdir(parents=True, exist_ok=False)
        ref_out = refs_dir(tmp)
        ref_out.mkdir(parents=True, exist_ok=False)

        _copy_table(conn, TABLE_TRANSACTIONS, tmp / TRANSACTIONS_PARQUET)
        _copy_table(conn, TABLE_AWARDS, tmp / AWARDS_PARQUET)

        for table, filename in _REF_PARQUET.items():
            _copy_table(conn, table, ref_out / filename)

        reject_count = _reject_count(conn)
        if reject_count > 0:
            _copy_table(conn, TABLE_REJECTS, tmp / REJECTS_PARQUET)

        sets_dir(data_root).mkdir(parents=True, exist_ok=True)
        tmp.rename(out)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    return out

def publish_set(
    conn: duckdb.DuckDBPyConnection,
    *,
    data_root: Path,
    run_id: str,
    allow_rejects: bool = False,
) -> PublishResult:
    """Integrity-check, write Parquet set, and conditionally flip `CURRENT`.

    #### Workflow:
        - Integrity failure → raise `IntegrityError` (no set write, no `CURRENT`)
        - `reject_count > 0` and not `allow_rejects` → write set, no `CURRENT`
        - Otherwise write set and atomically publish `CURRENT`
    """

    integrity = check_integrity(conn)
    if not integrity.ok:
        raise IntegrityError(integrity)

    set_path = write_parquet_set(conn, data_root, run_id)
    reject_count = _reject_count(conn)
    wrote_rejects = reject_count > 0 and (set_path / REJECTS_PARQUET).is_file()

    published = False
    if reject_count == 0 or allow_rejects:
        write_current_atomic(data_root, run_id)
        published = True

    return PublishResult(
        run_id=run_id,
        set_path=set_path,
        published=published,
        wrote_rejects=wrote_rejects,
        reject_count=reject_count,
    )


# === Helpers ===

def _reject_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Count rows in `TABLE_REJECTS`."""
    
    exists = conn.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = ?
        """,
        [TABLE_REJECTS],
    ).fetchone()
    if exists is None or int(exists[0]) == 0:
        return 0
    return _scalar(conn, f"SELECT COUNT(*) FROM {quote_ident(TABLE_REJECTS)}")

def _copy_table(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    path: Path,
) -> None:
    """COPY a staging table to a Parquet file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.resolve().as_posix().replace("'", "''")  # Make Windows happy
    conn.execute(
        f"COPY {quote_ident(table)} TO '{target}' (FORMAT PARQUET)"
    )

def _scalar(conn: duckdb.DuckDBPyConnection, sql: str) -> int:
    """Execute a scalar SQL query and return the result."""
    
    row = conn.execute(sql).fetchone()
    assert row is not None
    return int(row[0])

def list_set_files(set_path: Path) -> Sequence[Path]:
    """Return expected parquet paths under a set (for debug/inspect)."""

    files = [
        set_path / TRANSACTIONS_PARQUET,
        set_path / AWARDS_PARQUET,
        *(set_path / "refs" / name for name in _REF_PARQUET.values()),
    ]
    rejects = set_path / REJECTS_PARQUET
    if rejects.is_file():
        files.append(rejects)
    return files
