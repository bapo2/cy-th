# cy_th/semantic/types.py

"""Typed models for semantic index metadata, hits, and build results."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# === Metadata ===

@dataclass(frozen=True, slots=True)
class SemanticMetadata:
    """Fingerprint recorded in `metadata.json` for a published semantic index."""

    run_id: str
    model_id: str
    model_revision: str | None
    embedding_dim: int
    normalize: bool
    metric: str
    query_prefix: str
    document_count: int
    text_budget: int
    sentence_transformers_version: str | None
    built_at: datetime


# === Hits / Search ===

@dataclass(frozen=True, slots=True)
class SemanticDocument:
    """One assembled Award semantic document ready to embed."""

    award_id: str
    document_id: str
    text: str

@dataclass(frozen=True, slots=True)
class SemanticHit:
    """One ranked semantic search hit."""

    award_id: str
    document_id: str
    score: float
    text: str

@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    """Optional counts for candidate-restricted searches."""

    candidate_count: int | None = None
    indexed_candidate_count: int | None = None

@dataclass(frozen=True, slots=True)
class SearchResult:
    """Ranked hits plus optional candidate diagnostics."""

    hits: tuple[SemanticHit, ...]
    diagnostics: SearchDiagnostics


# === Build ===

@dataclass(frozen=True, slots=True)
class SemanticBuildResult:
    """Summary of a successful `cyth semantic build`."""

    run_id: str
    data_root: Path
    semantic_path: Path
    document_count: int
    model_id: str
    forced: bool
