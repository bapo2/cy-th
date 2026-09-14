# cy_th/semantic/embed.py

"""Embedding backends for semantic index build and query encoding."""

# === Imports ===

from __future__ import annotations
from typing import Protocol, Sequence, runtime_checkable
import hashlib
import re
import numpy as np
import numpy.typing as npt

from cy_th.semantic.errors import MissingEmbeddingDepsError, SemanticError
from cy_th.semantic.paths import DEFAULT_MODEL_ID, EMBEDDING_DIM


# === Constants ===

_VECTOR_NORM_EPS: float = 1e-8
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


# === Protocol ===

@runtime_checkable
class Embedder(Protocol):
    """Batches of text → L2-normalized `float32` embedding rows."""

    @property
    def model_id(self) -> str: ...

    @property
    def model_revision(self) -> str | None: ...

    @property
    def embedding_dim(self) -> int: ...

    @property
    def sentence_transformers_version(self) -> str | None: ...

    def embed(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        """Embed `texts` as shape `(len(texts), embedding_dim)` float32 rows.

        Callers that persist vectors (build) must re-normalize and validate (don't assume Embedder output is trusted).
        """
        ...


# === Helpers ===

def l2_normalize_rows(matrix: npt.NDArray[np.floating]) -> npt.NDArray[np.float32]:
    """Return `float32` row-normalized copy (`0` rows stay zero)."""

    out = np.asarray(matrix, dtype=np.float32, order="C").copy()
    if out.ndim != 2:
        raise ValueError(f"expected 2-D embedding matrix, got shape {out.shape}")
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    np.divide(out, norms, out=out, where=norms > 0)
    return out

def prepare_document_embeddings(
    vectors: npt.NDArray[np.floating],
    *,
    expected_rows: int,
    expected_dim: int,
) -> npt.NDArray[np.float32]:
    """L2-normalize and validate one embedding batch (instead of blindly trusting Embedder output).

    Raises `SemanticError` on shape mismatch, non-finite values, or zero vectors.
    """

    if expected_rows < 0 or expected_dim <= 0:
        raise ValueError("expected_rows must be >= 0 and expected_dim must be > 0")
    raw = np.asarray(vectors)
    if raw.shape != (expected_rows, expected_dim):
        raise SemanticError(
            f"embedding batch shape {raw.shape} != ({expected_rows}, {expected_dim})"
        )
    if expected_rows == 0:
        return np.zeros((0, expected_dim), dtype=np.float32)
    if not np.isfinite(raw).all():
        raise SemanticError("embedding batch contains non-finite values")

    out = l2_normalize_rows(raw)
    norms = np.linalg.norm(out, axis=1)
    bad = np.flatnonzero(norms < _VECTOR_NORM_EPS)
    if bad.size:
        raise SemanticError(
            f"embedding batch contains zero vector(s) at local row(s) {bad.tolist()}"
        )
    return out

def require_sentence_transformers() -> tuple[object, str]:
    """Import sentence-transformers or raise `MissingEmbeddingDepsError`.

    #### Returns:
        `(SentenceTransformer class, package version string)`
    """

    try:
        from importlib import import_module
        from importlib.metadata import version

        module = import_module("sentence_transformers")
        sentence_transformer = getattr(module, "SentenceTransformer")
    except ImportError as exc:
        raise MissingEmbeddingDepsError() from exc

    try:
        st_version = version("sentence-transformers")
    except Exception:
        st_version = "unknown"
    return sentence_transformer, st_version


# === Fake (Tests + Smoke w/out Torch) ===

class FakeEmbedder:
    """Deterministic hash-seeded embedder (no Torch / network)."""

    def __init__(self, *, dim: int = EMBEDDING_DIM, model_id: str = "fake/deterministic-v1") -> None:
        if dim <= 0:
            raise ValueError("dim must be > 0")
        self._dim = dim
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str | None:
        return "test"

    @property
    def embedding_dim(self) -> int:
        return self._dim

    @property
    def sentence_transformers_version(self) -> str | None:
        return None

    def embed(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        rows = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], byteorder="little", signed=False)
            rng = np.random.default_rng(seed)
            rows[i] = rng.standard_normal(self._dim, dtype=np.float64).astype(np.float32)
        return l2_normalize_rows(rows)


# === `sentence-transformers` ===

class SentenceTransformerEmbedder:
    """Real `sentence-transformers` backend (requires `cy-th[semantic]`)."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        local_files_only: bool = False,
    ) -> None:
        cls, st_version = require_sentence_transformers()
        self._model_id = model_id
        self._st_version = st_version
        self._local_files_only = local_files_only
        # Lazy-load so import of this module never pulls Torch
        self._model: object | None = None
        self._SentenceTransformer = cls
        self._revision: str | None = None
        self._dim: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str | None:
        self._ensure_model()
        return self._revision

    @property
    def embedding_dim(self) -> int:
        self._ensure_model()
        assert self._dim is not None
        return self._dim

    @property
    def sentence_transformers_version(self) -> str | None:
        return self._st_version

    def embed(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        model = self._ensure_model()
        if not texts:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        vectors = model.encode(  # type: ignore[attr-defined]
            list(texts),
            normalize_embeddings=False,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        out = np.asarray(vectors, dtype=np.float32, order="C")
        if out.ndim != 2 or out.shape[1] != self.embedding_dim:
            raise RuntimeError(
                f"unexpected embedding shape {out.shape}; expected (*, {self.embedding_dim})"
            )
        # Build re-normalizes/validates; return raw float32 rows
        return np.ascontiguousarray(out, dtype=np.float32)

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model

        model = self._SentenceTransformer(  # type: ignore[operator]
            self._model_id,
            local_files_only=self._local_files_only,
        )
        self._model = model
        dim_fn = getattr(model, "get_embedding_dimension", None)
        if not callable(dim_fn):
            dim_fn = getattr(model, "get_sentence_embedding_dimension")
        self._dim = int(dim_fn())  # type: ignore[operator]
        self._revision = _resolve_model_revision(model, model_id=self._model_id)
        if self._dim != EMBEDDING_DIM and self._model_id == DEFAULT_MODEL_ID:
            raise RuntimeError(
                f"locked model {self._model_id!r} returned dim={self._dim}, expected {EMBEDDING_DIM}"
            )
        return model

def _resolve_model_revision(model: object, *, model_id: str) -> str | None:
    """Resolved revision hash for `model`, or `None` when unavailable.

    Ignores model id/path strings such as `config._name_or_path`. Prefer explicit revision attribute, then Hub `model_info(...).sha`.
    """

    for attr in ("revision", "_revision"):
        value = getattr(model, attr, None)
        if _is_revision_hash(value):
            return str(value).strip()

    return _hub_model_sha(model_id)

def _is_revision_hash(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return _GIT_SHA_RE.fullmatch(value.strip()) is not None

def _hub_model_sha(model_id: str) -> str | None:
    """Best-effort commit SHA from HuggingFace Hub metadata."""

    try:
        from importlib import import_module

        hub = import_module("huggingface_hub")
        model_info = getattr(hub, "model_info")
        info = model_info(model_id)
    except Exception:
        return None

    sha = getattr(info, "sha", None)
    if _is_revision_hash(sha):
        return str(sha).strip()
    return None
