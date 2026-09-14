# cy_th/query/resolve.py

"""Resolve qualifying Award IDs from projected Award / ref topology filters."""

# === Imports ===

from __future__ import annotations
from typing import Final, Sequence
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import TABLE_LOCATIONS
from cy_th.query.types import AwardFilters, LocationFilter, LocationRole
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
) -> frozenset[str]:
    """Return Award IDs matching projected topology filters (all predicates AND'd).

    #### Semantics:
        - `None` → unconstrained
        - Empty iterable → zero matches (we don't treat as "all")
    """

    filters = filters if filters is not None else AwardFilters()

    clauses: list[str] = []
    params: list[object] = []

    for field_name, column in _ID_LIST_FILTERS:
        values = getattr(filters, field_name)
        if values is None:
            continue
        if len(values) == 0:
            return frozenset()
        clauses.append(
            f"a.{quote_ident(column)} IN (SELECT UNNEST(?))"
        )
        params.append(list(values))

    if filters.location is not None:
        loc_sql, loc_params, empty = _location_clause(filters.location)
        if empty:
            return frozenset()
        clauses.append(loc_sql)
        params.extend(loc_params)

    a = quote_ident(TABLE_AWARDS)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT a.{quote_ident('award_id')} FROM {a} AS a{where}"
    rows = conn.execute(sql, params).fetchall()
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
