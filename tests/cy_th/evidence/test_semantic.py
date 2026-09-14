# tests/cy_th/evidence/test_semantic.py

"""Semantic search via `EvidenceSession` (`FakeEmbedder` + unavailable path)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.evidence.errors import SemanticUnavailableError
from cy_th.evidence.session import EvidenceSession
from cy_th.evidence.types import MAX_SEMANTIC_TOP_K
from cy_th.query.types import AwardFilters
from cy_th.semantic.embed import FakeEmbedder


# === Unavailable ===

def test_search_unavailable_without_index_keeps_structured_tools(
    evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cy_th.semantic.embed.SentenceTransformerEmbedder",
        FakeEmbedder,
    )
    with EvidenceSession.open(evidence_root) as ev:
        with pytest.raises(SemanticUnavailableError):
            ev.search_contract_work("engineering services", top_k=3)
        # Structured tools should remain usable
        resolved = ev.resolve_awards(AwardFilters(award_ids=["A1"]), preview_limit=1)
        assert resolved.count == 1
        cards = ev.get_award_evidence(award_ids=["A1"])
        assert cards.cards[0].award_id == "A1"


# === Search (`FakeEmbedder` Index) ===

def test_search_mints_selection_and_retains_hits(
    evidence_root_with_semantic: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cy_th.semantic.embed.SentenceTransformerEmbedder",
        FakeEmbedder,
    )
    with EvidenceSession.open(evidence_root_with_semantic) as ev:
        view = ev.search_contract_work("engineering services support", top_k=3)
        assert view.count == len(view.hits)
        assert view.count == ev._require_selection(view.selection).count
        assert 1 <= view.count <= 3
        assert all(hit.query == "engineering services support" for hit in view.hits)
        assert len(ev._semantic_hits) == len(view.hits)
        # Search retains hits separately; AwardCards not auto-hydrated
        assert len(ev._award_cards) == 0

def test_search_hits_retained_separately_per_query(
    evidence_root_with_semantic: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cy_th.semantic.embed.SentenceTransformerEmbedder",
        FakeEmbedder,
    )
    with EvidenceSession.open(evidence_root_with_semantic) as ev:
        first = ev.search_contract_work("alpha engineering", top_k=2)
        second = ev.search_contract_work("beta aircraft", top_k=2)
        assert len(ev._semantic_hits) == len(first.hits) + len(second.hits)
        assert {h.query for h in ev._semantic_hits} == {
            "alpha engineering",
            "beta aircraft",
        }

def test_search_candidates_and_top_k_clamp(
    evidence_root_with_semantic: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cy_th.semantic.embed.SentenceTransformerEmbedder",
        FakeEmbedder,
    )
    with EvidenceSession.open(evidence_root_with_semantic) as ev:
        seed = ev.resolve_awards(AwardFilters(award_ids=["A1", "A3"]), preview_limit=1)
        scoped = ev.search_contract_work(
            "engineering",
            top_k=5,
            candidates=seed.selection,
        )
        allowed = {"A1", "A3"}
        assert all(hit.award_id in allowed for hit in scoped.hits)

        clamped = ev.search_contract_work(
            "support",
            top_k=MAX_SEMANTIC_TOP_K + 25,
        )
        assert len(clamped.hits) <= MAX_SEMANTIC_TOP_K

def test_search_rejects_non_positive_top_k(
    evidence_root_with_semantic: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cy_th.semantic.embed.SentenceTransformerEmbedder",
        FakeEmbedder,
    )
    from cy_th.evidence.errors import InvalidEvidenceRequestError

    with EvidenceSession.open(evidence_root_with_semantic) as ev:
        with pytest.raises(InvalidEvidenceRequestError, match="top_k"):
            ev.search_contract_work("x", top_k=0)
