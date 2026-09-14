# tests/cy_th/evidence/test_tools.py

"""Evidence tool ops (composition, bounds, cards, retention)."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest

from cy_th.evidence.errors import InvalidEvidenceRequestError
from cy_th.evidence.session import EvidenceSession
from cy_th.evidence.types import (
    MAX_AGGREGATE_LIMIT,
    MAX_AWARD_CARD_LIMIT,
    MAX_TRAVERSAL_LIMIT,
)
from cy_th.query.types import (
    ActivityWindow,
    AwardActivityRow,
    AwardFilters,
    EntityKind,
    GroupBy,
)


# === Helpers ===

WINDOW = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 2, 28))


# === Resolve + Cards ===

def test_resolve_mints_ref_and_preview_cards(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        view = ev.resolve_awards(AwardFilters(award_ids=["A2", "A1"]), preview_limit=2)
        assert view.count == 2
        assert view.selection.id.endswith("_0001")
        assert len(view.preview) == 2
        # Preview is award_id ASC
        assert [c.award_id for c in view.preview] == ["A1", "A2"]
        card = view.preview[0]
        assert card.piid == "PIID-A1"
        assert card.recipient_name == "Alpha Corp"
        assert card.awarding_agency_name == "Department of Defense"
        assert card.usaspending_permalink == "https://example.test/award/A1"
        assert card.place_of_performance is not None
        assert card.place_of_performance.state_code == "VA"
        # Registry retains cards by award_id
        assert set(ev._award_cards) == {"A1", "A2"}

def test_get_award_evidence_selection_and_ids(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        resolved = ev.resolve_awards(
            AwardFilters(award_ids=["A1", "A2", "A3"]),
            preview_limit=1,
        )
        from_sel = ev.get_award_evidence(selection=resolved.selection, limit=2)
        assert [c.award_id for c in from_sel.cards] == ["A1", "A2"]

        from_ids = ev.get_award_evidence(award_ids=["A3", "A1"], limit=10)
        assert [c.award_id for c in from_ids.cards] == ["A3", "A1"]

def test_get_award_evidence_dedupes_award_ids(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        view = ev.get_award_evidence(
            award_ids=["A1", "A1", "A2", "A1"],
            limit=10,
        )
        assert [c.award_id for c in view.cards] == ["A1", "A2"]

def test_get_award_evidence_requires_exactly_one_source(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        ref = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1).selection
        with pytest.raises(InvalidEvidenceRequestError, match="exactly one"):
            ev.get_award_evidence()
        with pytest.raises(InvalidEvidenceRequestError, match="exactly one"):
            ev.get_award_evidence(selection=ref, award_ids=["A1"])

def test_get_award_evidence_empty_sources(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        empty_ids = ev.get_award_evidence(award_ids=[], limit=5)
        assert empty_ids.cards == ()

        empty_sel = ev.resolve_awards(AwardFilters(award_ids=[]), preview_limit=1)
        assert empty_sel.count == 0
        from_empty = ev.get_award_evidence(selection=empty_sel.selection, limit=5)
        assert from_empty.cards == ()

def test_get_award_evidence_and_traverse_reject_bad_limits(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        ref = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1).selection
        with pytest.raises(InvalidEvidenceRequestError, match="limit"):
            ev.get_award_evidence(award_ids=["A1"], limit=0)
        with pytest.raises(InvalidEvidenceRequestError, match="limit"):
            ev.traverse_relationships(ref, limit=0)

def test_get_award_evidence_rejects_oversized_unique_ids(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        oversized = [f"X{i}" for i in range(MAX_AWARD_CARD_LIMIT + 1)]
        with pytest.raises(InvalidEvidenceRequestError, match="exceeds max"):
            ev.get_award_evidence(award_ids=oversized)


# === Bounds ===

def test_limits_reject_non_positive_and_clamp(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        with pytest.raises(InvalidEvidenceRequestError, match="preview_limit"):
            ev.resolve_awards(preview_limit=0)

        ref = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1)
        with pytest.raises(InvalidEvidenceRequestError, match="limit"):
            ev.aggregate_activity(ref.selection, WINDOW, limit=-1)

        preview = ev.resolve_awards(
            AwardFilters(award_ids=["A1", "A2", "A3", "A4"]),
            preview_limit=MAX_AWARD_CARD_LIMIT + 10,
        )
        assert len(preview.preview) <= MAX_AWARD_CARD_LIMIT

        agg = ev.aggregate_activity(
            preview.selection,
            WINDOW,
            limit=MAX_AGGREGATE_LIMIT + 50,
        )
        assert len(agg.rows) <= MAX_AGGREGATE_LIMIT

        trav = ev.traverse_relationships(
            preview.selection,
            limit=MAX_TRAVERSAL_LIMIT + 50,
        )
        assert len(trav.entities) <= MAX_TRAVERSAL_LIMIT


# === Aggregate / Traverse / Composition ===

def test_aggregate_over_selection_ref(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        resolved = ev.resolve_awards(
            AwardFilters(award_ids=["A1", "A2", "A3"]),
            preview_limit=1,
        )
        view = ev.aggregate_activity(
            resolved.selection,
            WINDOW,
            group_by=GroupBy.AWARD,
            limit=2,
        )
        assert view.derived_from == resolved.selection
        assert len(view.rows) == 2
        assert isinstance(view.rows[0], AwardActivityRow)
        assert isinstance(view.rows[1], AwardActivityRow)
        assert [view.rows[0].award_id, view.rows[1].award_id] == ["A2", "A1"]
        assert view.rows[0].total_obligation == Decimal("200.00")
        assert len(ev._aggregates) == 1
        assert ev._aggregates[0].derived_from == resolved.selection

def test_traverse_retains_full_set_and_truncates_view(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        resolved = ev.resolve_awards(AwardFilters(), preview_limit=1)
        tiny = ev.traverse_relationships(resolved.selection, limit=1)
        retained = ev._traversals[-1]
        assert len(tiny.entities) == 1
        assert len(retained.entities) > 1
        assert tiny.truncated is True
        assert tiny.derived_from == resolved.selection

        # include=() still empty through the facade
        empty = ev.traverse_relationships(resolved.selection, include=(), limit=10)
        assert empty.entities == ()
        assert empty.truncated is False

def test_composition_resolve_traverse_aggregate(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        seed = ev.resolve_awards(AwardFilters(award_ids=["A1", "A2"]), preview_limit=2)
        trav = ev.traverse_relationships(seed.selection, limit=20)
        recipients = [
            e.entity_id for e in trav.entities if e.kind is EntityKind.RECIPIENT
        ]
        assert "UEI_ALPHA" in recipients or "UEI_BETA" in recipients

        handoff = ev.resolve_awards(
            AwardFilters(recipient_ids=["UEI_ALPHA"]),
            preview_limit=2,
        )
        assert handoff.count == 2  # A1, A3
        assert handoff.selection.id != seed.selection.id

        agg = ev.aggregate_activity(handoff.selection, WINDOW, limit=5)
        assert agg.derived_from == handoff.selection
        award_ids: set[str] = set()
        for row in agg.rows:
            assert isinstance(row, AwardActivityRow)
            award_ids.add(row.award_id)
        assert award_ids <= {"A1", "A3"}

def test_award_card_registry_dedupes_by_id(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1)
        assert list(ev._award_cards) == ["A1"]
        ev.get_award_evidence(award_ids=["A1", "A1"])
        assert list(ev._award_cards) == ["A1"]
