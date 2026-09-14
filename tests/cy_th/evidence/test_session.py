# tests/cy_th/evidence/test_session.py

"""EvidenceSession lifecycle, opaque refs, and registry isolation."""

# === Imports ===

from __future__ import annotations
from datetime import date
from pathlib import Path
import pytest

from cy_th.evidence.errors import (
    ClosedEvidenceSessionError,
    InvalidSelectionRefError,
)
from cy_th.evidence.session import EvidenceSession
from cy_th.evidence.types import SelectionRef
from cy_th.query.types import ActivityWindow, AwardFilters


# === Helpers ===

WINDOW = ActivityWindow(from_date=date(2025, 1, 1), to_date=date(2025, 2, 28))


# === Lifecycle ===

def test_open_close_and_context_manager(evidence_root: Path) -> None:
    ev = EvidenceSession.open(evidence_root)
    assert ev.run_id.startswith("20260914T")
    resolved = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1)
    assert resolved.count == 1
    ev.close()
    with pytest.raises(ClosedEvidenceSessionError):
        ev.resolve_awards(AwardFilters(award_ids=["A1"]))

    with EvidenceSession.open(evidence_root) as session:
        view = session.resolve_awards(AwardFilters(award_ids=["A2"]), preview_limit=1)
        assert view.count == 1
    with pytest.raises(ClosedEvidenceSessionError):
        session.get_award_evidence(award_ids=["A2"])

def test_data_root_property(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        assert ev.data_root == evidence_root

def test_close_is_idempotent(evidence_root: Path) -> None:
    ev = EvidenceSession.open(evidence_root)
    ev.close()
    ev.close()


# === Selection Refs ===

def test_unknown_selection_ref_fails(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        with pytest.raises(InvalidSelectionRefError, match="sel_missing"):
            ev.aggregate_activity(SelectionRef("sel_missing"), WINDOW)

def test_foreign_session_ref_fails(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as a:
        foreign = a.resolve_awards(
            AwardFilters(award_ids=["A1"]), preview_limit=1
        ).selection
        assert foreign.id.endswith("_0001")

    with EvidenceSession.open(evidence_root) as b:
        local = b.resolve_awards(
            AwardFilters(award_ids=["A2"]), preview_limit=1
        ).selection
        assert local.id != foreign.id
        assert local.id.endswith("_0001")
        with pytest.raises(InvalidSelectionRefError, match=foreign.id):
            b.aggregate_activity(foreign, WINDOW)
        rows = b.aggregate_activity(local, WINDOW, limit=5)
        assert rows.derived_from == local

def test_post_close_ref_fails(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        ref = ev.resolve_awards(
            AwardFilters(award_ids=["A1"]), preview_limit=1
        ).selection
    with pytest.raises(ClosedEvidenceSessionError):
        ev.aggregate_activity(ref, WINDOW)

def test_selection_ids_include_session_token(evidence_root: Path) -> None:
    with EvidenceSession.open(evidence_root) as ev:
        first = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1)
        second = ev.resolve_awards(AwardFilters(award_ids=["A2"]), preview_limit=1)
        assert first.selection.id.startswith("sel_")
        assert first.selection.id.endswith("_0001")
        assert second.selection.id.endswith("_0002")
        token = first.selection.id.removeprefix("sel_").rsplit("_", 1)[0]
        assert second.selection.id == f"sel_{token}_0002"
