# cy_th/query/aggregate.py

"""Deterministic activity aggregation over qualifying Awards + date windows."""

# === Imports ===

from __future__ import annotations
from decimal import Decimal
from typing import Collection, Literal, overload
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import TABLE_RECIPIENTS
from cy_th.materialize.transactions import TABLE_TRANSACTIONS
from cy_th.query.types import (
    ActivityWindow,
    AwardActivityRow,
    GroupBy,
    RecipientActivityRow,
)
from cy_th.schema.db_types import quote_ident


# === Public API ===

@overload
def aggregate_activity(  # Overload for `AwardActivityRow` to make type-checker happy
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    window: ActivityWindow,
    *,
    group_by: Literal[GroupBy.AWARD] = GroupBy.AWARD,
    limit: int | None = None,
) -> list[AwardActivityRow]: ...

@overload
def aggregate_activity(  # Overload for `RecipientActivityRow` to make type-checker happy
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    window: ActivityWindow,
    *,
    group_by: Literal[GroupBy.RECIPIENT],
    limit: int | None = None,
) -> list[RecipientActivityRow]: ...

def aggregate_activity(
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    window: ActivityWindow,
    *,
    group_by: GroupBy = GroupBy.AWARD,
    limit: int | None = None,
) -> list[AwardActivityRow] | list[RecipientActivityRow]:
    """Sum `federal_action_obligation` for qualifying Awards in an activity window.

    #### Semantics:
        - Empty `award_ids` → empty result (we don't treat as "all")
        - Inclusive `[from_date, to_date]` on `transaction_fact.action_date`
        - Null obligations ignored inside `SUM` & null-total groups excluded
        - Ranked by `total_obligation DESC`, then stable ID `ASC`
    """

    if window.from_date > window.to_date:
        raise ValueError(
            f"ActivityWindow.from_date ({window.from_date}) must be <= to_date ({window.to_date})"
        )
    if limit is not None and limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")

    if not award_ids:
        return []

    if group_by is GroupBy.AWARD:
        return _aggregate_by_award(conn, award_ids, window, limit=limit)
    if group_by is GroupBy.RECIPIENT:
        return _aggregate_by_recipient(conn, award_ids, window, limit=limit)
    raise ValueError(f"unsupported group_by: {group_by!r}")  # Purely defensive, likely unreachable


# === Award Grouping ===

def _aggregate_by_award(
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    window: ActivityWindow,
    *,
    limit: int | None,
) -> list[AwardActivityRow]:
    """Group / rank activity by Award."""

    t = quote_ident(TABLE_TRANSACTIONS)
    a = quote_ident(TABLE_AWARDS)
    sql = f"""
        SELECT
          a.{quote_ident('award_id')} AS award_id,
          SUM(t.{quote_ident('federal_action_obligation')}) AS total_obligation,
          COUNT(*)::BIGINT AS transaction_count,
          a.{quote_ident('recipient_id')} AS recipient_id,
          a.{quote_ident('piid')} AS piid,
          a.{quote_ident('usaspending_permalink')} AS usaspending_permalink
        FROM {t} AS t
        INNER JOIN {a} AS a
          ON a.{quote_ident('award_id')} = t.{quote_ident('award_id')}
        WHERE t.{quote_ident('award_id')} IN (SELECT UNNEST(?))
          AND t.{quote_ident('action_date')} BETWEEN ? AND ?
        GROUP BY
          a.{quote_ident('award_id')},
          a.{quote_ident('recipient_id')},
          a.{quote_ident('piid')},
          a.{quote_ident('usaspending_permalink')}
        HAVING SUM(t.{quote_ident('federal_action_obligation')}) IS NOT NULL
        ORDER BY total_obligation DESC, award_id ASC
    """
    params: list[object] = [list(award_ids), window.from_date, window.to_date]
    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        AwardActivityRow(
            award_id=str(row[0]),
            total_obligation=_as_decimal(row[1]),
            transaction_count=int(row[2]),
            recipient_id=_as_optional_str(row[3]),
            piid=_as_optional_str(row[4]),
            usaspending_permalink=_as_optional_str(row[5]),
        )
        for row in rows
    ]


# === Recipient Grouping ===

def _aggregate_by_recipient(
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    window: ActivityWindow,
    *,
    limit: int | None,
) -> list[RecipientActivityRow]:
    """Group / rank activity by recipient UEI."""

    t = quote_ident(TABLE_TRANSACTIONS)
    a = quote_ident(TABLE_AWARDS)
    r = quote_ident(TABLE_RECIPIENTS)
    sql = f"""
        SELECT
          a.{quote_ident('recipient_id')} AS recipient_id,
          SUM(t.{quote_ident('federal_action_obligation')}) AS total_obligation,
          COUNT(*)::BIGINT AS transaction_count,
          r.{quote_ident('name')} AS name
        FROM {t} AS t
        INNER JOIN {a} AS a
          ON a.{quote_ident('award_id')} = t.{quote_ident('award_id')}
        LEFT JOIN {r} AS r
          ON r.{quote_ident('uei')} = a.{quote_ident('recipient_id')}
        WHERE t.{quote_ident('award_id')} IN (SELECT UNNEST(?))
          AND t.{quote_ident('action_date')} BETWEEN ? AND ?
          AND a.{quote_ident('recipient_id')} IS NOT NULL
        GROUP BY
          a.{quote_ident('recipient_id')},
          r.{quote_ident('name')}
        HAVING SUM(t.{quote_ident('federal_action_obligation')}) IS NOT NULL
        ORDER BY total_obligation DESC, recipient_id ASC
    """
    params: list[object] = [list(award_ids), window.from_date, window.to_date]
    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        RecipientActivityRow(
            recipient_id=str(row[0]),
            total_obligation=_as_decimal(row[1]),
            transaction_count=int(row[2]),
            name=_as_optional_str(row[3]),
        )
        for row in rows
    ]


# === Helpers ===

def _as_decimal(value: object) -> Decimal:
    """Coerce DuckDB numeric values to `Decimal`."""

    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _as_optional_str(value: object) -> str | None:
    """Coerce a DuckDB value to `str | None`."""

    if value is None:
        return None
    return str(value)
