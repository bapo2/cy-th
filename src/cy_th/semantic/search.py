# cy_th/semantic/search.py

"""Chunked exact cosine scoring over a memmapped embedding matrix."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
import heapq
from typing import Sequence
import numpy as np
import numpy.typing as npt


# === Candidates ===

@dataclass(slots=True)
class ScoredRow:
    """One scored embedding row before hit materialization."""

    row_index: int
    award_id: str
    score: float


# === Heap Entry ===

@dataclass(slots=True)
class _HeapEntry:
    """Min-heap entry where smaller = worse retained hit (worst-of-best ordering)."""

    score: float
    award_id: str
    row_index: int

    def __lt__(self, other: _HeapEntry) -> bool:
        if self.score != other.score:
            return self.score < other.score
        return self.award_id > other.award_id


# === Scoring ===

def top_k_from_matrix(
    matrix: npt.NDArray[np.float32],
    query: npt.NDArray[np.float32],
    award_ids: Sequence[str],
    *,
    top_k: int,
    min_score: float | None,
    chunk_size: int,
    row_indices: npt.NDArray[np.int64] | None = None,
) -> list[ScoredRow]:
    """Exact cosine (dot) search with deterministic `score DESC`, `award_id ASC` top-k.

    When `row_indices` is `None`, scores the full matrix in chunks, else scores only those rows (also chunked).
    """

    if top_k <= 0:
        raise ValueError("top_k must be > 0")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if query.ndim != 1:
        raise ValueError(f"query must be 1-D, got shape {query.shape}")
    if matrix.ndim != 2 or matrix.shape[1] != query.shape[0]:
        raise ValueError(
            f"matrix shape {matrix.shape} incompatible with query length {query.shape[0]}"
        )
    if len(award_ids) != matrix.shape[0]:
        raise ValueError("award_ids length must match matrix rows")

    q = np.asarray(query, dtype=np.float32).reshape(-1)
    heap: list[_HeapEntry] = []

    if row_indices is None:
        n = matrix.shape[0]
        for start in range(0, n, chunk_size):
            stop = min(start + chunk_size, n)
            _accumulate_chunk(
                heap,
                scores=matrix[start:stop] @ q,
                row_start=start,
                award_ids=award_ids,
                top_k=top_k,
                min_score=min_score,
                index_map=None,
            )
    else:
        if row_indices.ndim != 1:
            raise ValueError("row_indices must be 1-D")
        for start in range(0, int(row_indices.shape[0]), chunk_size):
            stop = min(start + chunk_size, int(row_indices.shape[0]))
            idx = row_indices[start:stop]
            _accumulate_chunk(
                heap,
                scores=matrix[idx] @ q,
                row_start=0,
                award_ids=award_ids,
                top_k=top_k,
                min_score=min_score,
                index_map=idx,
            )

    ranked = sorted(heap, key=lambda e: (-e.score, e.award_id))
    return [
        ScoredRow(row_index=e.row_index, award_id=e.award_id, score=float(e.score))
        for e in ranked
    ]

def _accumulate_chunk(
    heap: list[_HeapEntry],
    *,
    scores: npt.NDArray[np.floating],
    row_start: int,
    award_ids: Sequence[str],
    top_k: int,
    min_score: float | None,
    index_map: npt.NDArray[np.int64] | None,
) -> None:
    for offset, score in enumerate(scores):
        value = float(score)
        if min_score is not None and value < min_score:
            continue
        if index_map is None:
            row_index = row_start + offset
        else:
            row_index = int(index_map[offset])
        award_id = award_ids[row_index]
        entry = _HeapEntry(score=value, award_id=award_id, row_index=row_index)
        if len(heap) < top_k:
            heapq.heappush(heap, entry)
        elif entry.score > heap[0].score or (
            entry.score == heap[0].score and entry.award_id < heap[0].award_id
        ):
            heapq.heapreplace(heap, entry)
