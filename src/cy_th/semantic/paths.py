# cy_th/semantic/paths.py

"""On-disk layout helpers for derived semantic indexes."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
from typing import Final

from cy_th.materialize.paths import is_run_id


# === Constants ===

DERIVED_DIRNAME: Final[str] = "derived"
SEMANTIC_DIRNAME: Final[str] = "semantic"
SEMANTIC_STAGING_DIRNAME: Final[str] = ".tmp-semantic"

DOCUMENTS_PARQUET: Final[str] = "documents.parquet"
EMBEDDINGS_NPY: Final[str] = "embeddings.npy"
METADATA_JSON: Final[str] = "metadata.json"

DEFAULT_MODEL_ID: Final[str] = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: Final[int] = 384
TEXT_BUDGET: Final[int] = 1800
METRIC_COSINE: Final[str] = "cosine"
DEFAULT_EMBED_BATCH_SIZE: Final[int] = 64
DEFAULT_SEARCH_CHUNK_SIZE: Final[int] = 8192


# === Document IDs ===

def document_id_for_award(award_id: str) -> str:
    """Return the namespaced semantic document ID for an Award."""

    return f"award:{award_id}"


# === Derived Roots ===

def derived_dir(root: Path) -> Path:
    """Resolve `<root>/derived/`."""

    return root / DERIVED_DIRNAME

def derived_run_dir(root: Path, run_id: str) -> Path:
    """Resolve `<root>/derived/<run-id>/`."""

    if not is_run_id(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return derived_dir(root) / run_id

def semantic_dir(root: Path, run_id: str) -> Path:
    """Resolve the published semantic index dir (`.../semantic/`)."""

    return derived_run_dir(root, run_id) / SEMANTIC_DIRNAME

def semantic_staging_dir(root: Path, run_id: str) -> Path:
    """Resolve the semantic build staging dir (`.../.tmp-semantic/`)."""

    return derived_run_dir(root, run_id) / SEMANTIC_STAGING_DIRNAME


# === Artifact Paths ===

def documents_path(semantic_root: Path) -> Path:
    """Resolve `documents.parquet` under a semantic directory."""

    return semantic_root / DOCUMENTS_PARQUET

def embeddings_path(semantic_root: Path) -> Path:
    """Resolve `embeddings.npy` under a semantic directory."""

    return semantic_root / EMBEDDINGS_NPY

def metadata_path(semantic_root: Path) -> Path:
    """Resolve `metadata.json` under a semantic directory."""

    return semantic_root / METADATA_JSON
