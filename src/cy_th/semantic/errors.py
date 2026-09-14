# cy_th/semantic/errors.py

"""Errors raised when building or searching the semantic index."""

# === Imports ===

from __future__ import annotations
from pathlib import Path


# === Base ===

class SemanticError(RuntimeError):
    """Base class for semantic index failures."""


# === Build ===

class MissingEmbeddingDepsError(SemanticError):
    """Raised when `cyth semantic build` is run without `cy-th[semantic]`."""

    def __init__(self, detail: str | None = None) -> None:
        hint = "install with: uv sync --extra semantic  (or pip install 'cy-th[semantic]')"
        msg = detail if detail is not None else "sentence-transformers is not installed"
        super().__init__(f"{msg}; {hint}")
        self.detail = detail

class SemanticIndexExistsError(SemanticError):
    """Raised when a published semantic index already exists and `--force` was not set."""

    def __init__(self, *, run_id: str, semantic_path: Path) -> None:
        self.run_id = run_id
        self.semantic_path = semantic_path
        super().__init__(
            f"semantic index already exists for run {run_id} at {semantic_path} "
            "(pass --force to rebuild)"
        )


# === Open / Search ===

class MissingSemanticIndexError(SemanticError):
    """Raised when the published semantic directory or required artifacts are absent."""

    def __init__(self, *, run_id: str, semantic_path: Path, detail: str) -> None:
        self.run_id = run_id
        self.semantic_path = semantic_path
        self.detail = detail
        super().__init__(
            f"missing semantic index for run {run_id}: {detail} ({semantic_path})"
        )

class IncompatibleSemanticIndexError(SemanticError):
    """Raised when published artifacts do not match the pinned dataset / locked config."""

    def __init__(self, *, run_id: str, detail: str) -> None:
        self.run_id = run_id
        self.detail = detail
        super().__init__(f"incompatible semantic index for run {run_id}: {detail}")

class InvalidSemanticQueryError(SemanticError):
    """Raised for blank queries or invalid / zero query embeddings."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"invalid semantic query: {detail}")

class ClosedSemanticIndexError(SemanticError):
    """Raised when searching a closed or session-invalidated `SemanticIndex`."""

    def __init__(self, detail: str = "SemanticIndex is closed") -> None:
        self.detail = detail
        super().__init__(detail)
