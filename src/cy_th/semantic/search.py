# cy_th/semantic/search.py

"""Chunked exact cosine scoring over a memmapped embedding matrix."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
import heapq
from typing import Iterator
import numpy as np
import numpy.typing as npt


# === Candidates ===

@dataclass(slots=True)
class ScoredRow:
    """One scored embedding row before hit materialization."""

    row_index: int
    award_id: str
    score: float

@dataclass(slots=True)
class IdChunk:
    """One bounded chunk of `(row_index, award_id)` pairs aligned for scoring."""

    row_indices: npt.NDArray[np.int64]
    award_ids: tuple[str, ...]


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

def top_k_from_id_chunks(
    matrix: npt.NDArray[np.float32],
    query: npt.NDArray[np.float32],
    chunks: Iterator[IdChunk],
    *,
    top_k: int,
    min_score: float | None,
) -> list[ScoredRow]:
    """Exact cosine (dot) search over streamed identity chunks; retain only a top-k heap.

    Each chunk supplies aligned `row_indices` / `award_ids`. Embedding rows are gathered from the memmap for that chunk only.
    """

    if top_k <= 0:
        raise ValueError("top_k must be > 0")
    if query.ndim != 1:
        raise ValueError(f"query must be 1-D, got shape {query.shape}")
    if matrix.ndim != 2 or matrix.shape[1] != query.shape[0]:
        raise ValueError(
            f"matrix shape {matrix.shape} incompatible with query length {query.shape[0]}"
        )

    q = np.asarray(query, dtype=np.float32).reshape(-1)
    heap: list[_HeapEntry] = []

    for chunk in chunks:
        if chunk.row_indices.shape[0] != len(chunk.award_ids):
            raise ValueError("row_indices and award_ids chunk lengths must match")
        if chunk.row_indices.size == 0:
            continue
        scores = matrix[chunk.row_indices] @ q
        for offset, score in enumerate(scores):
            value = float(score)
            if min_score is not None and value < min_score:
                continue
            entry = _HeapEntry(
                score=value,
                award_id=chunk.award_ids[offset],
                row_index=int(chunk.row_indices[offset]),
            )
            if len(heap) < top_k:
                heapq.heappush(heap, entry)
            elif entry.score > heap[0].score or (
                entry.score == heap[0].score and entry.award_id < heap[0].award_id
            ):
                heapq.heapreplace(heap, entry)

    ranked = sorted(heap, key=lambda e: (-e.score, e.award_id))
    return [
        ScoredRow(row_index=e.row_index, award_id=e.award_id, score=float(e.score))
        for e in ranked
    ]
