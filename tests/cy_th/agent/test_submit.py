# tests/cy_th/agent/test_submit.py

"""`submit_answer` parsing and citation filtering."""

# === Imports ===

from __future__ import annotations
import pytest

from cy_th.agent.errors import InvalidModelRequestError
from cy_th.agent.submit import (
    filter_citations,
    finalize_submit_answer,
)
from cy_th.evidence.types import AwardCard


# === Helpers ===

def _card(award_id: str) -> AwardCard:
    return AwardCard(award_id=award_id, recipient_name=f"R-{award_id}")


# === `filter_citations` ===

def test_filter_citations_keeps_acquired_drops_unknown() -> None:
    acquired = {"A1": _card("A1"), "A2": _card("A2")}
    result = filter_citations(["A1", "BAD", "A1", "A2", "BAD"], acquired)
    assert [c.award_id for c in result.citations] == ["A1", "A2"]
    assert result.dropped_citation_ids == ("BAD",)

def test_filter_citations_empty_ids() -> None:
    result = filter_citations([], {"A1": _card("A1")})
    assert result.citations == ()
    assert result.dropped_citation_ids == ()


# === `finalize_submit_answer` ===

def test_finalize_submit_answer_filters_citations() -> None:
    submitted = finalize_submit_answer(
        {
            "answer": "  Alpha won.  ",
            "citation_award_ids": ["A1", "NOPE"],
        },
        acquired={"A1": _card("A1")},
    )
    assert submitted.answer == "Alpha won."
    assert [c.award_id for c in submitted.citations] == ["A1"]
    assert submitted.dropped_citation_ids == ("NOPE",)

def test_finalize_rejects_blank_answer() -> None:
    with pytest.raises(InvalidModelRequestError, match="non-empty"):
        finalize_submit_answer(
            {"answer": "   ", "citation_award_ids": []},
            acquired={},
        )

def test_finalize_requires_citation_array() -> None:
    with pytest.raises(InvalidModelRequestError, match="citation_award_ids"):
        finalize_submit_answer({"answer": "ok"}, acquired={})
