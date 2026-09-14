# tests/cy_th/semantic/test_search.py

"""Unit tests for chunked exact cosine top-k scoring."""

# === Imports ===

from __future__ import annotations
import numpy as np
import pytest

from cy_th.semantic.search import IdChunk, top_k_from_id_chunks


# === Ranking ===

def test_top_k_orders_by_score_then_award_id() -> None:
    # 0→A_C (med), 1→A_A (high), 2→A_B (high, later id), 3→A_D (low)
    matrix = np.array(
        [
            [0.5, 0.0],
            [1.0, 0.0],
            [1.0, 0.0],
            [0.1, 0.0],
        ],
        dtype=np.float32,
    )
    query = np.array([1.0, 0.0], dtype=np.float32)
    chunks = iter(
        [
            IdChunk(
                row_indices=np.array([0, 1], dtype=np.int64),
                award_ids=("A_C", "A_A"),
            ),
            IdChunk(
                row_indices=np.array([2, 3], dtype=np.int64),
                award_ids=("A_B", "A_D"),
            ),
        ]
    )
    ranked = top_k_from_id_chunks(matrix, query, chunks, top_k=3, min_score=None)
    assert [r.award_id for r in ranked] == ["A_A", "A_B", "A_C"]
    assert ranked[0].score == pytest.approx(1.0)
    assert ranked[1].score == pytest.approx(1.0)
    assert ranked[2].score == pytest.approx(0.5)

def test_min_score_filters_weak_hits() -> None:
    matrix = np.array([[1.0], [0.4], [0.2]], dtype=np.float32)
    query = np.array([1.0], dtype=np.float32)
    chunks = iter(
        [
            IdChunk(
                row_indices=np.array([0, 1, 2], dtype=np.int64),
                award_ids=("A1", "A2", "A3"),
            )
        ]
    )
    ranked = top_k_from_id_chunks(matrix, query, chunks, top_k=10, min_score=0.5)
    assert [r.award_id for r in ranked] == ["A1"]

def test_empty_chunks_and_top_k_validation() -> None:
    matrix = np.ones((1, 2), dtype=np.float32)
    query = np.ones(2, dtype=np.float32)
    empty = top_k_from_id_chunks(
        matrix,
        query,
        iter([IdChunk(row_indices=np.zeros(0, dtype=np.int64), award_ids=())]),
        top_k=1,
        min_score=None,
    )
    assert empty == []
    with pytest.raises(ValueError, match="top_k"):
        top_k_from_id_chunks(
            matrix,
            query,
            iter([]),
            top_k=0,
            min_score=None,
        )

def test_chunk_length_mismatch_and_query_shape() -> None:
    matrix = np.ones((2, 2), dtype=np.float32)
    query = np.ones(2, dtype=np.float32)
    with pytest.raises(ValueError, match="chunk lengths"):
        top_k_from_id_chunks(
            matrix,
            query,
            iter(
                [
                    IdChunk(
                        row_indices=np.array([0], dtype=np.int64),
                        award_ids=("A1", "A2"),
                    )
                ]
            ),
            top_k=1,
            min_score=None,
        )
    with pytest.raises(ValueError, match="1-D"):
        top_k_from_id_chunks(
            matrix,
            np.ones((1, 2), dtype=np.float32),
            iter([]),
            top_k=1,
            min_score=None,
        )
    with pytest.raises(ValueError, match="incompatible"):
        top_k_from_id_chunks(
            matrix,
            np.ones(3, dtype=np.float32),
            iter([]),
            top_k=1,
            min_score=None,
        )
