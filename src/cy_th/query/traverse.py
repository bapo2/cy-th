# cy_th/query/traverse.py

"""One-hop deterministic relationship traversal from an AwardSelection."""

# === Imports ===

from __future__ import annotations
from typing import Collection, Final, Iterable
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_CLASSIFICATIONS,
    TABLE_IDVS,
    TABLE_LOCATIONS,
    TABLE_OFFICES,
    TABLE_RECIPIENTS,
)
from cy_th.query.types import (
    AwardSelection,
    EntityKind,
    RelatedEntity,
    RelationRole,
    TraversalResult,
)
from cy_th.schema.db_types import quote_ident
from cy_th.schema.enums import AgencyTier, ClassificationKind


# === Constants ===

_KIND_ORDER: Final[dict[EntityKind, int]] = {
    kind: index for index, kind in enumerate(EntityKind)
}
_ROLE_ORDER: Final[dict[RelationRole, int]] = {
    role: index for index, role in enumerate(RelationRole)
}
_TIER_ORDER: Final[dict[AgencyTier, int]] = {
    tier: index for index, tier in enumerate(AgencyTier)
}

_ALL_KINDS: Final[frozenset[EntityKind]] = frozenset(EntityKind)


# === Public API ===

def traverse_relationships(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
    *,
    include: Collection[EntityKind] | None = None,
) -> TraversalResult:
    """Expand `selection` into related canonical entities (one-hop Award topology).

    #### Semantics:
        - `include=None` → all `EntityKind` values
        - `include=()` → empty result
        - Null Award FKs and non-joining refs are omitted
        - Dedupe `(kind, role, entity_id)`; sort kind → role (`None` first) → agency_tier (`None` first) → entity_id
    """

    kinds = _resolve_include(include)
    if not kinds or selection.count == 0:
        return TraversalResult(entities=())

    entities: list[RelatedEntity] = []
    if EntityKind.RECIPIENT in kinds:
        entities.extend(_recipients(conn, selection))
    if EntityKind.AGENCY in kinds:
        entities.extend(_agencies(conn, selection))
    if EntityKind.OFFICE in kinds:
        entities.extend(_offices(conn, selection))
    if EntityKind.IDV in kinds:
        entities.extend(_idvs(conn, selection))
    if EntityKind.LOCATION in kinds:
        entities.extend(_locations(conn, selection))
    if EntityKind.CLASSIFICATION in kinds:
        entities.extend(_classifications(conn, selection))

    return TraversalResult(entities=_dedupe_and_sort(entities))


# === Include ===

def _resolve_include(include: Collection[EntityKind] | None) -> frozenset[EntityKind]:
    if include is None:
        return _ALL_KINDS
    kinds: set[EntityKind] = set()
    for item in include:
        if not isinstance(item, EntityKind):
            raise ValueError(
                f"include entries must be EntityKind, got {type(item).__name__}: {item!r}"
            )
        kinds.add(item)
    return frozenset(kinds)


# === Dedupe / Sort ===

def _dedupe_and_sort(entities: Iterable[RelatedEntity]) -> tuple[RelatedEntity, ...]:
    unique: dict[tuple[EntityKind, RelationRole | None, str], RelatedEntity] = {}
    for entity in entities:
        key = (entity.kind, entity.role, entity.entity_id)
        unique.setdefault(key, entity)
    return tuple(sorted(unique.values(), key=_sort_key))

def _sort_key(
    entity: RelatedEntity,
) -> tuple[int, int, int, str]:
    role_rank = -1 if entity.role is None else _ROLE_ORDER[entity.role]
    tier_rank = -1 if entity.agency_tier is None else _TIER_ORDER[entity.agency_tier]
    return (_KIND_ORDER[entity.kind], role_rank, tier_rank, entity.entity_id)


# === Edge Queries ===

def _recipients(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    r = quote_ident(TABLE_RECIPIENTS)
    rows = conn.execute(
        f"""
        SELECT DISTINCT
          a.{quote_ident('recipient_id')} AS entity_id,
          r.{quote_ident('name')} AS label
        FROM {a} AS a
        INNER JOIN {s} AS sel
          ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
        INNER JOIN {r} AS r
          ON r.{quote_ident('uei')} = a.{quote_ident('recipient_id')}
        WHERE a.{quote_ident('recipient_id')} IS NOT NULL
        """
    ).fetchall()
    return [
        RelatedEntity(
            kind=EntityKind.RECIPIENT,
            role=None,
            entity_id=str(row[0]),
            label=_optional_str(row[1]),
        )
        for row in rows
    ]

def _agencies(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    edges: tuple[tuple[str, RelationRole, AgencyTier], ...] = (
        ("awarding_agency_id", RelationRole.AWARDING, AgencyTier.TOPTIER),
        ("awarding_sub_agency_id", RelationRole.AWARDING, AgencyTier.SUBTIER),
        ("funding_agency_id", RelationRole.FUNDING, AgencyTier.TOPTIER),
        ("funding_sub_agency_id", RelationRole.FUNDING, AgencyTier.SUBTIER),
    )
    out: list[RelatedEntity] = []
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    ag = quote_ident(TABLE_AGENCIES)
    for fk, role, tier in edges:
        rows = conn.execute(
            f"""
            SELECT DISTINCT
              a.{quote_ident(fk)} AS entity_id,
              ag.{quote_ident('name')} AS label
            FROM {a} AS a
            INNER JOIN {s} AS sel
              ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
            INNER JOIN {ag} AS ag
              ON ag.{quote_ident('agency_id')} = a.{quote_ident(fk)}
            WHERE a.{quote_ident(fk)} IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            out.append(
                RelatedEntity(
                    kind=EntityKind.AGENCY,
                    role=role,
                    entity_id=str(row[0]),
                    label=_optional_str(row[1]),
                    agency_tier=tier,
                )
            )
    return out

def _offices(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    edges: tuple[tuple[str, RelationRole], ...] = (
        ("awarding_office_id", RelationRole.AWARDING),
        ("funding_office_id", RelationRole.FUNDING),
    )
    out: list[RelatedEntity] = []
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    o = quote_ident(TABLE_OFFICES)
    for fk, role in edges:
        rows = conn.execute(
            f"""
            SELECT DISTINCT
              a.{quote_ident(fk)} AS entity_id,
              o.{quote_ident('name')} AS label
            FROM {a} AS a
            INNER JOIN {s} AS sel
              ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
            INNER JOIN {o} AS o
              ON o.{quote_ident('office_id')} = a.{quote_ident(fk)}
            WHERE a.{quote_ident(fk)} IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            out.append(
                RelatedEntity(
                    kind=EntityKind.OFFICE,
                    role=role,
                    entity_id=str(row[0]),
                    label=_optional_str(row[1]),
                )
            )
    return out

def _idvs(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    i = quote_ident(TABLE_IDVS)
    rows = conn.execute(
        f"""
        SELECT DISTINCT
          a.{quote_ident('parent_idv_id')} AS entity_id,
          i.{quote_ident('piid')} AS label,
          i.{quote_ident('award_key_agency_id')} AS idv_agency_id
        FROM {a} AS a
        INNER JOIN {s} AS sel
          ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
        INNER JOIN {i} AS i
          ON i.{quote_ident('idv_id')} = a.{quote_ident('parent_idv_id')}
        WHERE a.{quote_ident('parent_idv_id')} IS NOT NULL
        """
    ).fetchall()
    return [
        RelatedEntity(
            kind=EntityKind.IDV,
            role=None,
            entity_id=str(row[0]),
            label=_optional_str(row[1]),
            idv_agency_id=_optional_str(row[2]),
        )
        for row in rows
    ]

def _locations(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    edges: tuple[tuple[str, RelationRole], ...] = (
        ("recipient_location_id", RelationRole.RECIPIENT),
        ("place_of_performance_id", RelationRole.PLACE_OF_PERFORMANCE),
    )
    out: list[RelatedEntity] = []
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    loc = quote_ident(TABLE_LOCATIONS)
    for fk, role in edges:
        rows = conn.execute(
            f"""
            SELECT DISTINCT
              a.{quote_ident(fk)} AS entity_id,
              loc.{quote_ident('country_code')} AS country_code,
              loc.{quote_ident('state_code')} AS state_code,
              loc.{quote_ident('county_fips')} AS county_fips,
              loc.{quote_ident('city_name')} AS city_name,
              loc.{quote_ident('zip_code')} AS zip_code,
              loc.{quote_ident('granularity')} AS granularity
            FROM {a} AS a
            INNER JOIN {s} AS sel
              ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
            INNER JOIN {loc} AS loc
              ON loc.{quote_ident('location_id')} = a.{quote_ident(fk)}
            WHERE a.{quote_ident(fk)} IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            out.append(
                RelatedEntity(
                    kind=EntityKind.LOCATION,
                    role=role,
                    entity_id=str(row[0]),
                    label=None,
                    country_code=_optional_str(row[1]),
                    state_code=_optional_str(row[2]),
                    county_fips=_optional_str(row[3]),
                    city_name=_optional_str(row[4]),
                    zip_code=_optional_str(row[5]),
                    granularity=_optional_str(row[6]),
                )
            )
    return out

def _classifications(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
) -> list[RelatedEntity]:
    edges: tuple[tuple[str, ClassificationKind], ...] = (
        ("naics_id", ClassificationKind.NAICS),
        ("psc_id", ClassificationKind.PSC),
    )
    out: list[RelatedEntity] = []
    a = quote_ident(TABLE_AWARDS)
    s = quote_ident(selection.relation_name)
    c = quote_ident(TABLE_CLASSIFICATIONS)
    for fk, kind in edges:
        rows = conn.execute(
            f"""
            SELECT DISTINCT
              a.{quote_ident(fk)} AS entity_id,
              c.{quote_ident('code')} AS code,
              c.{quote_ident('description')} AS description
            FROM {a} AS a
            INNER JOIN {s} AS sel
              ON a.{quote_ident('award_id')} = sel.{quote_ident('award_id')}
            INNER JOIN {c} AS c
              ON c.{quote_ident('classification_id')} = a.{quote_ident(fk)}
            WHERE a.{quote_ident(fk)} IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            code = str(row[1])
            description = _optional_str(row[2])
            out.append(
                RelatedEntity(
                    kind=EntityKind.CLASSIFICATION,
                    role=None,
                    entity_id=str(row[0]),
                    label=description if description is not None else code,
                    classification_kind=kind,
                    code=code,
                    description=description,
                )
            )
    return out


# === Helpers ===

def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
