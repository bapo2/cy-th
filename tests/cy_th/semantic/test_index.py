# tests/cy_th/semantic/test_index.py

"""SemanticIndex open / search / session / handoff tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
from typing import Sequence
import numpy as np
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.query.errors import StaleSelectionError
from cy_th.query.types import AwardFilters
from cy_th.semantic.build import build_semantic_index
from cy_th.semantic.embed import FakeEmbedder
from cy_th.semantic.errors import (
    ClosedSemanticIndexError,
    IncompatibleSemanticIndexError,
    InvalidSemanticQueryError,
    MissingSemanticIndexError,
)
from cy_th.semantic.index import SemanticIndex
from cy_th.semantic.paths import QUERY_PREFIX, semantic_dir


# === Recording Embedder ===

class RecordingEmbedder(FakeEmbedder):
    """`FakeEmbedder` that records `embed()` inputs (for query-prefix checks)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append([str(t) for t in texts])
        return super().embed(texts)

class ZeroQueryEmbedder(FakeEmbedder):
    """Returns a zero vector for any query (documents stay `FakeEmbedder`-like)."""

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if len(texts) == 1 and str(texts[0]).startswith(QUERY_PREFIX):
            return np.zeros((1, self.embedding_dim), dtype=np.float32)
        return super().embed(texts)


# === Open / Search ===

def test_search_is_deterministic_and_prefixes_query(
    built_semantic_root: Path,
) -> None:
    embedder = RecordingEmbedder()
    with ProcurementDataset.open(built_semantic_root) as ds:
        with SemanticIndex.open(ds, embedder, chunk_size=2) as index:
            assert index.document_count == 4
            assert index.metadata.query_prefix == QUERY_PREFIX
            a = index.search("detection systems", top_k=3)
            b = index.search("detection systems", top_k=3)
            assert [h.award_id for h in a.hits] == [h.award_id for h in b.hits]
            assert [h.score for h in a.hits] == [h.score for h in b.hits]
            assert len(a.hits) == 3
            for hit in a.hits:
                assert hit.document_id == f"award:{hit.award_id}"
                assert hit.text
                assert hit.award_id != "A_EMPTY"

    # First search call after open should embed the prefixed query
    query_calls = [c for c in embedder.calls if len(c) == 1]
    assert query_calls
    assert query_calls[0][0] == f"{QUERY_PREFIX}detection systems"

def test_blank_query_rejected(built_semantic_root: Path, fake_embedder: FakeEmbedder) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        with SemanticIndex.open(ds, fake_embedder) as index:
            with pytest.raises(InvalidSemanticQueryError, match="blank"):
                index.search("   ")

def test_zero_query_embedding_rejected(built_semantic_root: Path) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        # Build used `FakeEmbedder` revision "test"; `ZeroQueryEmbedder` matches that
        with SemanticIndex.open(ds, ZeroQueryEmbedder()) as index:
            with pytest.raises(InvalidSemanticQueryError, match="zero"):
                index.search("anything")

def test_min_score_can_drop_all_hits(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        with SemanticIndex.open(ds, fake_embedder) as index:
            result = index.search("radar", top_k=10, min_score=0.999999)
            assert result.hits == ()


# === Candidates / Handoff ===

def test_candidates_restrict_and_skip_nonindexed(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        selection = ds.select_awards(["A_FOOD", "A_EMPTY", "A_RADAR"])
        with SemanticIndex.open(ds, fake_embedder, chunk_size=1) as index:
            result = index.search(
                "meals",
                candidates=selection,
                top_k=10,
            )
            assert result.diagnostics.candidate_count == 3
            # A_EMPTY has no semantic row
            assert result.diagnostics.indexed_candidate_count == 2
            ids = {h.award_id for h in result.hits}
            assert ids <= {"A_FOOD", "A_RADAR"}
            assert "A_EMPTY" not in ids

            handoff = ds.select_awards([h.award_id for h in result.hits])
            assert handoff.count == len(result.hits)

def test_stale_candidates_rejected(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds1:
        selection = ds1.resolve_awards(AwardFilters())
    with ProcurementDataset.open(built_semantic_root) as ds2:
        with SemanticIndex.open(ds2, fake_embedder) as index:
            with pytest.raises(StaleSelectionError):
                index.search("x", candidates=selection, top_k=1)


# === Lifecycle / Compat ===

def test_closed_index_and_closed_dataset(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    ds = ProcurementDataset.open(built_semantic_root)
    index = SemanticIndex.open(ds, fake_embedder)
    index.close()
    with pytest.raises(ClosedSemanticIndexError):
        index.search("x")
    index.close()  # Idempotent

    ds2 = ProcurementDataset.open(built_semantic_root)
    index2 = SemanticIndex.open(ds2, fake_embedder)
    ds2.close()
    with pytest.raises(ClosedSemanticIndexError, match="session"):
        index2.search("x")
    index2.close()

def test_missing_index_open_fails(
    semantic_data_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(semantic_data_root) as ds:
        with pytest.raises(MissingSemanticIndexError):
            SemanticIndex.open(ds, fake_embedder)

def test_embedder_dim_and_revision_mismatch(
    built_semantic_root: Path,
) -> None:
    class _DimMismatch(FakeEmbedder):
        @property
        def embedding_dim(self) -> int:  # type: ignore[override]
            return 16

    class _RevisionMismatch(FakeEmbedder):
        @property
        def model_revision(self) -> str | None:  # type: ignore[override]
            return "deadbeef"

    with ProcurementDataset.open(built_semantic_root) as ds:
        with pytest.raises(IncompatibleSemanticIndexError, match="dim"):
            SemanticIndex.open(ds, _DimMismatch())
        with pytest.raises(IncompatibleSemanticIndexError, match="model_revision"):
            SemanticIndex.open(ds, _RevisionMismatch())

def test_open_rejects_bad_chunk_size_and_top_k(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        with pytest.raises(ValueError, match="chunk_size"):
            SemanticIndex.open(ds, fake_embedder, chunk_size=0)
        with SemanticIndex.open(ds, fake_embedder) as index:
            with pytest.raises(ValueError, match="top_k"):
                index.search("x", top_k=0)
            assert index.run_id == ds.run_id
            assert index.semantic_path == semantic_dir(built_semantic_root, ds.run_id)

def test_projection_includes_txn_only_award(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        with SemanticIndex.open(ds, fake_embedder) as index:
            result = index.search("Unique newer transaction work", top_k=4)
            ids = {h.award_id for h in result.hits}
            assert "A_TXN" in ids
            txn_hit = next(h for h in result.hits if h.award_id == "A_TXN")
            assert "Unique newer transaction work" in txn_hit.text
            assert "Award description:" not in txn_hit.text
