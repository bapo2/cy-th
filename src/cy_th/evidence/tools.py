# cy_th/evidence/tools.py

"""Thin evidence-tool operations over query / semantic / traversal primitives."""

# === Imports ===

from __future__ import annotations
from typing import TYPE_CHECKING, Collection, Sequence
import duckdb

from cy_th.evidence.errors import InvalidEvidenceRequestError
from cy_th.evidence.types import (
    DEFAULT_AGGREGATE_LIMIT,
    DEFAULT_AWARD_CARD_LIMIT,
    DEFAULT_SEMANTIC_TOP_K,
    DEFAULT_TRAVERSAL_LIMIT,
    MAX_AGGREGATE_LIMIT,
    MAX_AWARD_CARD_LIMIT,
    MAX_SEMANTIC_TOP_K,
    MAX_TRAVERSAL_LIMIT,
    AggregateEvidence,
    AggregateResultView,
    AwardCard,
    AwardEvidenceView,
    PlaceOfPerformanceSummary,
    ResolveResultView,
    SearchResultView,
    SelectionRef,
    SemanticHitEvidence,
    TraversalEvidence,
    TraversalResultView,
    clamp_bound,
)
from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_CLASSIFICATIONS,
    TABLE_LOCATIONS,
    TABLE_OFFICES,
    TABLE_RECIPIENTS,
)
from cy_th.query.types import (
    ActivityWindow,
    AwardFilters,
    AwardSelection,
    EntityKind,
    GroupBy,
)
from cy_th.schema.db_types import quote_ident

if TYPE_CHECKING:
    from cy_th.evidence.session import EvidenceSession


# === Public Ops ===

def search_contract_work(
    session: EvidenceSession,
    query: str,
    *,
    top_k: int = DEFAULT_SEMANTIC_TOP_K,
    min_score: float | None = None,
    candidates: SelectionRef | None = None,
) -> SearchResultView:
    """Semantic discovery → mint a selection from hit Award IDs."""

    try:
        bound_k = clamp_bound(top_k, maximum=MAX_SEMANTIC_TOP_K, name="top_k")
    except ValueError as exc:
        raise InvalidEvidenceRequestError(str(exc)) from exc

    candidate_selection = None
    if candidates is not None:
        candidate_selection = session._require_selection(candidates)

    index = session._ensure_semantic()
    result = index.search(
        query,
        candidates=candidate_selection,
        top_k=bound_k,
        min_score=min_score,
    )

    hits = tuple(
        SemanticHitEvidence(
            award_id=hit.award_id,
            score=hit.score,
            text=hit.text,
            document_id=hit.document_id,
            query=query,
        )
        for hit in result.hits
    )
    for hit in hits:
        session._retain_semantic_hit(hit)

    award_ids = [hit.award_id for hit in hits]
    selection = session.dataset.select_awards(award_ids)
    ref = session._mint_selection(
        selection,
        source="search_contract_work",
        detail=query,
    )
    return SearchResultView(selection=ref, count=selection.count, hits=hits)

def resolve_awards(
    session: EvidenceSession,
    filters: AwardFilters | None = None,
    *,
    preview_limit: int = DEFAULT_AWARD_CARD_LIMIT,
) -> ResolveResultView:
    """Structured filters → mint a selection + bounded Award card preview."""

    try:
        bound = clamp_bound(
            preview_limit, maximum=MAX_AWARD_CARD_LIMIT, name="preview_limit"
        )
    except ValueError as exc:
        raise InvalidEvidenceRequestError(str(exc)) from exc

    selection = session.dataset.resolve_awards(filters)
    detail = "AwardFilters()" if filters is None else repr(filters)
    ref = session._mint_selection(
        selection,
        source="resolve_awards",
        detail=detail,
    )
    preview_ids = _selection_award_ids_ordered(
        session.dataset.conn, selection, limit=bound
    )
    preview = tuple(_hydrate_and_retain(session, preview_ids))
    return ResolveResultView(selection=ref, count=selection.count, preview=preview)

def aggregate_activity(
    session: EvidenceSession,
    selection: SelectionRef,
    window: ActivityWindow,
    *,
    group_by: GroupBy = GroupBy.AWARD,
    limit: int = DEFAULT_AGGREGATE_LIMIT,
) -> AggregateResultView:
    """Deterministic obligation aggregation over a selection ref."""

    try:
        bound = clamp_bound(limit, maximum=MAX_AGGREGATE_LIMIT, name="limit")
    except ValueError as exc:
        raise InvalidEvidenceRequestError(str(exc)) from exc

    internal = session._require_selection(selection)
    rows = session.dataset.aggregate_activity(
        internal,
        window,
        group_by=group_by,
        limit=bound,
    )
    row_tuple = tuple(rows)
    evidence = AggregateEvidence(
        derived_from=selection,
        group_by=group_by,
        rows=row_tuple,  # type: ignore[arg-type]
    )
    session._retain_aggregate(evidence)
    return AggregateResultView(
        derived_from=selection,
        group_by=group_by,
        rows=row_tuple,  # type: ignore[arg-type]
    )

def traverse_relationships(
    session: EvidenceSession,
    selection: SelectionRef,
    *,
    include: Collection[EntityKind] | None = None,
    limit: int = DEFAULT_TRAVERSAL_LIMIT,
) -> TraversalResultView:
    """One-hop related entities over a selection ref (view bounded)."""

    try:
        bound = clamp_bound(limit, maximum=MAX_TRAVERSAL_LIMIT, name="limit")
    except ValueError as exc:
        raise InvalidEvidenceRequestError(str(exc)) from exc

    internal = session._require_selection(selection)
    result = session.dataset.traverse_relationships(internal, include=include)
    evidence = TraversalEvidence(derived_from=selection, entities=result.entities)
    session._retain_traversal(evidence)

    view_entities = result.entities[:bound]
    truncated = len(result.entities) > bound
    return TraversalResultView(
        derived_from=selection,
        entities=view_entities,
        truncated=truncated,
    )

def get_award_evidence(
    session: EvidenceSession,
    *,
    selection: SelectionRef | None = None,
    award_ids: Sequence[str] | None = None,
    limit: int = DEFAULT_AWARD_CARD_LIMIT,
) -> AwardEvidenceView:
    """Hydrate bounded Award citation cards from exactly one source."""

    if (selection is None) == (award_ids is None):
        raise InvalidEvidenceRequestError(
            "provide exactly one of selection or award_ids"
        )

    try:
        bound = clamp_bound(limit, maximum=MAX_AWARD_CARD_LIMIT, name="limit")
    except ValueError as exc:
        raise InvalidEvidenceRequestError(str(exc)) from exc

    if award_ids is not None:
        # Dedupe first so outward cards match registry canonical identity
        unique_ids = list(dict.fromkeys(award_ids))
        if len(unique_ids) > MAX_AWARD_CARD_LIMIT:
            raise InvalidEvidenceRequestError(
                f"award_ids length {len(unique_ids)} exceeds max {MAX_AWARD_CARD_LIMIT}"
            )
        target_ids = unique_ids[:bound]
    else:
        assert selection is not None
        internal = session._require_selection(selection)
        target_ids = _selection_award_ids_ordered(
            session.dataset.conn, internal, limit=bound
        )

    cards = tuple(_hydrate_and_retain(session, target_ids))
    return AwardEvidenceView(cards=cards)


# === Card Hydration ===

def hydrate_award_cards(
    conn: duckdb.DuckDBPyConnection,
    award_ids: Sequence[str],
) -> list[AwardCard]:
    """Load Award citation cards for `award_ids` (order preserved; missing are skipped)."""

    if not award_ids:
        return []

    a = quote_ident(TABLE_AWARDS)
    r = quote_ident(TABLE_RECIPIENTS)
    ag = quote_ident(TABLE_AGENCIES)
    o = quote_ident(TABLE_OFFICES)
    cl = quote_ident(TABLE_CLASSIFICATIONS)
    loc = quote_ident(TABLE_LOCATIONS)

    rows = conn.execute(
        f"""
        SELECT
          a.{quote_ident('award_id')},
          a.{quote_ident('piid')},
          a.{quote_ident('award_type_code')},
          a.{quote_ident('recipient_id')},
          rec.{quote_ident('name')},
          a.{quote_ident('base_description')},
          a.{quote_ident('awarding_agency_id')},
          aw.{quote_ident('name')},
          a.{quote_ident('awarding_sub_agency_id')},
          aws.{quote_ident('name')},
          a.{quote_ident('awarding_office_id')},
          ofc.{quote_ident('name')},
          a.{quote_ident('naics_id')},
          naics.{quote_ident('code')},
          naics.{quote_ident('description')},
          a.{quote_ident('psc_id')},
          psc.{quote_ident('code')},
          psc.{quote_ident('description')},
          a.{quote_ident('place_of_performance_id')},
          pop.{quote_ident('country_code')},
          pop.{quote_ident('state_code')},
          pop.{quote_ident('county_fips')},
          pop.{quote_ident('city_name')},
          pop.{quote_ident('zip_code')},
          pop.{quote_ident('granularity')},
          a.{quote_ident('usaspending_permalink')}
        FROM {a} AS a
        LEFT JOIN {r} AS rec
          ON rec.{quote_ident('uei')} = a.{quote_ident('recipient_id')}
        LEFT JOIN {ag} AS aw
          ON aw.{quote_ident('agency_id')} = a.{quote_ident('awarding_agency_id')}
        LEFT JOIN {ag} AS aws
          ON aws.{quote_ident('agency_id')} = a.{quote_ident('awarding_sub_agency_id')}
        LEFT JOIN {o} AS ofc
          ON ofc.{quote_ident('office_id')} = a.{quote_ident('awarding_office_id')}
        LEFT JOIN {cl} AS naics
          ON naics.{quote_ident('classification_id')} = a.{quote_ident('naics_id')}
        LEFT JOIN {cl} AS psc
          ON psc.{quote_ident('classification_id')} = a.{quote_ident('psc_id')}
        LEFT JOIN {loc} AS pop
          ON pop.{quote_ident('location_id')} = a.{quote_ident('place_of_performance_id')}
        WHERE a.{quote_ident('award_id')} IN (SELECT UNNEST(?))
        """,
        [list(award_ids)],
    ).fetchall()

    by_id = {_optional_str(row[0]): _card_from_row(row) for row in rows}
    # Preserve caller order; skip ids absent from published set
    return [by_id[aid] for aid in award_ids if aid in by_id]


# === Helpers ===

def _hydrate_and_retain(
    session: EvidenceSession,
    award_ids: Sequence[str],
) -> list[AwardCard]:
    cards = hydrate_award_cards(session.dataset.conn, award_ids)
    session._upsert_award_cards(cards)
    return cards

def _selection_award_ids_ordered(
    conn: duckdb.DuckDBPyConnection,
    selection: AwardSelection,
    *,
    limit: int,
) -> list[str]:
    """First `limit` Award IDs from a selection, ordered by `award_id ASC`."""

    if selection.count == 0 or limit <= 0:
        return []

    qname = quote_ident(selection.relation_name)
    rows = conn.execute(
        f"""
        SELECT {quote_ident('award_id')}
        FROM {qname}
        ORDER BY {quote_ident('award_id')} ASC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [str(row[0]) for row in rows]

def _card_from_row(row: tuple[object, ...]) -> AwardCard:
    pop_id = _optional_str(row[18])
    if pop_id is None:
        pop: PlaceOfPerformanceSummary | None = None
    else:
        pop = PlaceOfPerformanceSummary(
            location_id=pop_id,
            country_code=_optional_str(row[19]),
            state_code=_optional_str(row[20]),
            county_fips=_optional_str(row[21]),
            city_name=_optional_str(row[22]),
            zip_code=_optional_str(row[23]),
            granularity=_optional_str(row[24]),
        )

    return AwardCard(
        award_id=str(row[0]),
        piid=_optional_str(row[1]),
        award_type_code=_optional_str(row[2]),
        recipient_id=_optional_str(row[3]),
        recipient_name=_optional_str(row[4]),
        base_description=_optional_str(row[5]),
        awarding_agency_id=_optional_str(row[6]),
        awarding_agency_name=_optional_str(row[7]),
        awarding_sub_agency_id=_optional_str(row[8]),
        awarding_sub_agency_name=_optional_str(row[9]),
        awarding_office_id=_optional_str(row[10]),
        awarding_office_name=_optional_str(row[11]),
        naics_id=_optional_str(row[12]),
        naics_code=_optional_str(row[13]),
        naics_description=_optional_str(row[14]),
        psc_id=_optional_str(row[15]),
        psc_code=_optional_str(row[16]),
        psc_description=_optional_str(row[17]),
        place_of_performance=pop,
        usaspending_permalink=_optional_str(row[25]),
    )

def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
