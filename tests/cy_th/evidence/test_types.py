# tests/cy_th/evidence/test_types.py

"""Tests for evidence bounds helpers and outward serialization."""

# === Imports ===

from __future__ import annotations
from decimal import Decimal
import pytest

from cy_th.evidence.types import (
    MAX_SEMANTIC_TOP_K,
    AggregateResultView,
    AwardCard,
    PlaceOfPerformanceSummary,
    SearchResultView,
    SelectionRef,
    SemanticHitEvidence,
    clamp_bound,
)
from cy_th.query.types import AwardActivityRow, GroupBy


# === `clamp_bound` ===

def test_clamp_bound_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="top_k must be > 0"):
        clamp_bound(0, maximum=MAX_SEMANTIC_TOP_K, name="top_k")
    with pytest.raises(ValueError, match="top_k must be > 0"):
        clamp_bound(-3, maximum=MAX_SEMANTIC_TOP_K, name="top_k")

def test_clamp_bound_caps_to_maximum() -> None:
    assert clamp_bound(10, maximum=MAX_SEMANTIC_TOP_K, name="top_k") == 10
    assert clamp_bound(100, maximum=MAX_SEMANTIC_TOP_K, name="top_k") == MAX_SEMANTIC_TOP_K


# === `to_dict` ===

def test_selection_ref_and_card_to_dict() -> None:
    ref = SelectionRef(id="sel_abc_0001")
    assert ref.to_dict() == {"id": "sel_abc_0001"}
    assert str(ref) == "sel_abc_0001"

    card = AwardCard(
        award_id="A1",
        piid="P1",
        place_of_performance=PlaceOfPerformanceSummary(state_code="VA"),
    )
    payload = card.to_dict()
    assert payload["award_id"] == "A1"
    assert payload["place_of_performance"]["state_code"] == "VA"
    assert payload["recipient_name"] is None

def test_view_to_dict_covers_remaining_views() -> None:
    from cy_th.evidence.types import (
        AwardEvidenceView,
        ResolveResultView,
        TraversalResultView,
    )
    from cy_th.query.types import EntityKind, RelatedEntity

    resolve = ResolveResultView(
        selection=SelectionRef("sel_x_0001"),
        count=1,
        preview=(AwardCard(award_id="A1"),),
    )
    assert resolve.to_dict()["preview"][0]["award_id"] == "A1"

    trav = TraversalResultView(
        derived_from=SelectionRef("sel_x_0001"),
        entities=(
            RelatedEntity(
                kind=EntityKind.RECIPIENT,
                role=None,
                entity_id="UEI",
                label="X",
            ),
        ),
        truncated=False,
    )
    assert trav.to_dict()["entities"][0]["kind"] == "recipient"

    evid = AwardEvidenceView(cards=(AwardCard(award_id="A1"),))
    assert evid.to_dict()["cards"][0]["award_id"] == "A1"

    view = SearchResultView(
        selection=SelectionRef("sel_x_0001"),
        count=1,
        hits=(
            SemanticHitEvidence(
                award_id="A1",
                score=0.5,
                text="hello",
                document_id="award:A1",
                query="q",
            ),
        ),
    )
    assert view.to_dict()["hits"][0]["award_id"] == "A1"

    agg = AggregateResultView(
        derived_from=SelectionRef("sel_x_0001"),
        group_by=GroupBy.AWARD,
        rows=(
            AwardActivityRow(
                award_id="A1",
                total_obligation=Decimal("12.50"),
                transaction_count=1,
                recipient_id="UEI",
                piid="P",
                usaspending_permalink=None,
            ),
        ),
    )
    payload = agg.to_dict()
    assert payload["group_by"] == "award"
    assert payload["rows"][0]["total_obligation"] == "12.50"
