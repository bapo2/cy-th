# cy_th/query/resolve.py

"""Resolve qualifying Award IDs into a session-scoped DuckDB selection."""

# === Imports ===

from __future__ import annotations
from typing import Collection, Final, Sequence
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import TABLE_LOCATIONS
from cy_th.query.types import AwardFilters, AwardSelection, LocationFilter, LocationRole
from cy_th.schema.db_types import quote_ident
from cy_th.schema.keys import normalize_city_name


# === Constants ===

# `(AwardFilters field, award_record column)` for exact ID-list predicates
_ID_LIST_FILTERS: Final[tuple[tuple[str, str], ...]] = (
    ("award_ids", "award_id"),
    ("recipient_ids", "recipient_id"),
    ("awarding_agency_ids", "awarding_agency_id"),
    ("awarding_sub_agency_ids", "awarding_sub_agency_id"),
    ("awarding_office_ids", "awarding_office_id"),
    ("funding_agency_ids", "funding_agency_id"),
    ("funding_sub_agency_ids", "funding_sub_agency_id"),
    ("funding_office_ids", "funding_office_id"),
    ("parent_idv_ids", "parent_idv_id"),
    ("naics_ids", "naics_id"),
    ("psc_ids", "psc_id"),
)

_LOCATION_FK: Final[dict[LocationRole, str]] = {
    LocationRole.RECIPIENT: "recipient_location_id",
    LocationRole.PLACE_OF_PERFORMANCE: "place_of_performance_id",
}


# === Public API ===

def resolve_awards(
    conn: duckdb.DuckDBPyConnection,
    filters: AwardFilters | None = None,
    *,
    relation_name: str,
    session_id: str,
) -> AwardSelection:
    """Materialize qualifying Award IDs into a temp table named `relation_name`.

    #### Semantics:
        - Filter list `None` → unconstrained
        - Empty iterable → zero matches (we don't treat as "all")
        - Result is an `AwardSelection` bound to `session_id` for JOIN-based aggregation
    """

    filters = filters if filters is not None else AwardFilters()
    qname = quote_ident(relation_name)

    clauses: list[str] = []
    params: list[object] = []

    for field_name, column in _ID_LIST_FILTERS:
        values = getattr(filters, field_name)
        if values is None:
            continue
        if len(values) == 0:
            return _empty_selection(
                conn, relation_name=relation_name, session_id=session_id
            )
        clauses.append(f"a.{quote_ident(column)} IN (SELECT UNNEST(?))")
        params.append(list(values))

    if filters.location is not None:
        loc_sql, loc_params, empty = _location_clause(filters.location)
        if empty:
            return _empty_selection(
                conn, relation_name=relation_name, session_id=session_id
            )
        clauses.append(loc_sql)
        params.extend(loc_params)

    a = quote_ident(TABLE_AWARDS)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    conn.execute(f"DROP TABLE IF EXISTS {qname}")
    conn.execute(
        f"""
        CREATE TEMP TABLE {qname} AS
        SELECT DISTINCT a.{quote_ident('award_id')} AS {quote_ident('award_id')}
        FROM {a} AS a
        {where}
        """,
        params,
    )
    return _selection_from_relation(
        conn, relation_name=relation_name, session_id=session_id
    )

def select_awards(
    conn: duckdb.DuckDBPyConnection,
    award_ids: Collection[str],
    *,
    relation_name: str,
    session_id: str,
) -> AwardSelection:
    """Materialize an `AwardSelection` from an explicit Award ID collection.

    Used by tests + semantic retrieval candidate handoff. Empty collections yield an empty selection (we don't treat as "all").
    """

    qname = quote_ident(relation_name)
    conn.execute(f"DROP TABLE IF EXISTS {qname}")
    if not award_ids:
        return _empty_selection(
            conn, relation_name=relation_name, session_id=session_id
        )

    conn.execute(
        f"""
        CREATE TEMP TABLE {qname} AS
        SELECT DISTINCT UNNEST(?) AS {quote_ident('award_id')}
        """,
        [list(award_ids)],
    )
    return _selection_from_relation(
        conn, relation_name=relation_name, session_id=session_id
    )

def selection_award_ids(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> frozenset[str]:
    """Fetch Award IDs from a selection into Python (tests/debug)."""

    if selection.count == 0:
        return frozenset()
    qname = quote_ident(selection.relation_name)
    rows = conn.execute(
        f"SELECT {quote_ident('award_id')} FROM {qname}"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


# === Location ===

def _location_clause(
    location: LocationFilter,
) -> tuple[str, list[object], bool]:
    """Build a location predicate against the role-specific Award FK.

    #### Returns:
        `(sql_fragment, params, empty)` where `empty` = zero matches
    """

    fk = _LOCATION_FK[location.role]
    a_fk = f"a.{quote_ident(fk)}"

    has_ids = location.location_ids is not None
    structured = _structured_location_predicates(location)

    if not has_ids and not structured:
        raise ValueError(
            "LocationFilter requires location_ids and/or at least one structured field"
        )

    if has_ids and len(location.location_ids or ()) == 0:
        return ("", [], True)

    parts: list[str] = []
    params: list[object] = []

    if has_ids:
        parts.append(f"{a_fk} IN (SELECT UNNEST(?))")
        params.append(list(location.location_ids or ()))

    if structured:
        exists_sql, exists_params = _structured_exists(a_fk, structured)
        parts.append(exists_sql)
        params.extend(exists_params)

    return (" AND ".join(parts), params, False)

def _structured_location_predicates(
    location: LocationFilter,
) -> list[tuple[str, str]]:
    """Return `(column, value)` pairs for exact `LocationRef` field matches."""

    preds: list[tuple[str, str]] = []
    if location.country_code is not None:
        preds.append(("country_code", location.country_code.strip()))
    if location.state_code is not None:
        preds.append(("state_code", location.state_code.strip()))
    if location.county_fips is not None:
        preds.append(("county_fips", location.county_fips.strip()))
    if location.city_name is not None:
        preds.append(("city_name", normalize_city_name(location.city_name)))
    if location.zip_code is not None:
        preds.append(("zip_code", location.zip_code.strip()))
    return preds

def _structured_exists(
    award_fk_expr: str,
    predicates: Sequence[tuple[str, str]],
) -> tuple[str, list[object]]:
    """`EXISTS` subquery joining `ref_locations` on the Award location FK."""

    loc = quote_ident(TABLE_LOCATIONS)
    where_parts = [
        f"loc.{quote_ident('location_id')} = {award_fk_expr}",
    ]
    params: list[object] = []
    for column, value in predicates:
        where_parts.append(f"loc.{quote_ident(column)} = ?")
        params.append(value)

    sql = (
        f"EXISTS (SELECT 1 FROM {loc} AS loc WHERE "
        + " AND ".join(where_parts)
        + ")"
    )
    return sql, params


# === Selection Helpers ===

def _empty_selection(
    conn: duckdb.DuckDBPyConnection,
    *,
    relation_name: str,
    session_id: str,
) -> AwardSelection:
    """Create an empty temp Award ID table."""

    qname = quote_ident(relation_name)
    conn.execute(f"DROP TABLE IF EXISTS {qname}")
    conn.execute(
        f"CREATE TEMP TABLE {qname} ({quote_ident('award_id')} VARCHAR)"
    )
    return AwardSelection(
        relation_name=relation_name, count=0, session_id=session_id
    )

def _selection_from_relation(
    conn: duckdb.DuckDBPyConnection,
    *,
    relation_name: str,
    session_id: str,
) -> AwardSelection:
    """Build `AwardSelection` metadata for an existing temp relation."""

    qname = quote_ident(relation_name)
    row = conn.execute(f"SELECT COUNT(*) FROM {qname}").fetchone()
    assert row is not None
    return AwardSelection(
        relation_name=relation_name,
        count=int(row[0]),
        session_id=session_id,
    )
