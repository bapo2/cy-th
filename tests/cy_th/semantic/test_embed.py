# tests/cy_th/semantic/test_embed.py

"""Tests for embedding helpers and `FakeEmbedder`."""

# === Imports ===

from __future__ import annotations
from typing import Any
import numpy as np
import pytest

from cy_th.semantic.embed import (
    FakeEmbedder,
    SentenceTransformerEmbedder,
    l2_normalize_rows,
    prepare_document_embeddings,
    require_sentence_transformers,
)
from cy_th.semantic.errors import MissingEmbeddingDepsError, SemanticError
from cy_th.semantic.paths import EMBEDDING_DIM, QUERY_PREFIX, format_query_text


# === Query Prefix ===

def test_format_query_text_applies_locked_prefix() -> None:
    assert format_query_text("detection systems") == (
        f"{QUERY_PREFIX}detection systems"
    )
    assert format_query_text("x", prefix="P:") == "P:x"


# === Normalize / Prepare ===

def test_l2_normalize_rows_unit_length() -> None:
    raw = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    out = l2_normalize_rows(raw)
    assert out.shape == (2, 2)
    assert abs(float(np.linalg.norm(out[0])) - 1.0) < 1e-6
    assert float(np.linalg.norm(out[1])) == 0.0

def test_l2_normalize_rejects_non_2d() -> None:
    with pytest.raises(ValueError, match="2-D"):
        l2_normalize_rows(np.array([1.0, 2.0], dtype=np.float32))

def test_prepare_document_embeddings_rejects_bad_batches() -> None:
    good = np.ones((2, 4), dtype=np.float32)
    prepared = prepare_document_embeddings(good, expected_rows=2, expected_dim=4)
    assert prepared.shape == (2, 4)
    assert np.allclose(np.linalg.norm(prepared, axis=1), 1.0)

    with pytest.raises(SemanticError, match="shape"):
        prepare_document_embeddings(good, expected_rows=3, expected_dim=4)

    with pytest.raises(ValueError, match="expected_dim"):
        prepare_document_embeddings(good, expected_rows=2, expected_dim=0)

    bad = np.array([[1.0, np.nan], [0.0, 1.0]], dtype=np.float32)
    with pytest.raises(SemanticError, match="non-finite"):
        prepare_document_embeddings(bad, expected_rows=2, expected_dim=2)

    zeros = np.zeros((1, 3), dtype=np.float32)
    with pytest.raises(SemanticError, match="zero vector"):
        prepare_document_embeddings(zeros, expected_rows=1, expected_dim=3)

    empty = prepare_document_embeddings(
        np.zeros((0, 3), dtype=np.float32),
        expected_rows=0,
        expected_dim=3,
    )
    assert empty.shape == (0, 3)


# === `FakeEmbedder` ===

def test_fake_embedder_is_deterministic_and_normalized() -> None:
    emb = FakeEmbedder(dim=EMBEDDING_DIM)
    a = emb.embed(["alpha", "beta"])
    b = emb.embed(["alpha", "beta"])
    assert a.shape == (2, EMBEDDING_DIM)
    assert np.allclose(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert not np.allclose(a[0], a[1])
    assert emb.embed([]).shape == (0, EMBEDDING_DIM)

def test_fake_embedder_rejects_nonpositive_dim() -> None:
    with pytest.raises(ValueError, match="dim"):
        FakeEmbedder(dim=0)


# === Deps / ST Backend (Mocked) ===

def test_require_sentence_transformers_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real_import_module = importlib.import_module

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("blocked for test")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _blocked)
    with pytest.raises(MissingEmbeddingDepsError, match="uv sync --extra semantic"):
        require_sentence_transformers()

def test_sentence_transformer_embedder_with_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubModel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.revision = "abc1234deadbeef"

        def get_embedding_dimension(self) -> int:
            return EMBEDDING_DIM

        def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
            return np.ones((len(texts), EMBEDDING_DIM), dtype=np.float32)

    monkeypatch.setattr(
        "cy_th.semantic.embed.require_sentence_transformers",
        lambda: (_StubModel, "9.9.9"),
    )
    emb = SentenceTransformerEmbedder("stub/model", local_files_only=True)
    assert emb.model_id == "stub/model"
    assert emb.sentence_transformers_version == "9.9.9"
    assert emb.embedding_dim == EMBEDDING_DIM
    assert emb.model_revision == "abc1234deadbeef"
    vectors = emb.embed(["a", "b"])
    assert vectors.shape == (2, EMBEDDING_DIM)
    assert emb.embed([]).shape == (0, EMBEDDING_DIM)

def test_sentence_transformer_rejects_wrong_locked_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadDim:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_embedding_dimension(self) -> int:
            return 16

    monkeypatch.setattr(
        "cy_th.semantic.embed.require_sentence_transformers",
        lambda: (_BadDim, "1.0"),
    )
    emb = SentenceTransformerEmbedder()
    with pytest.raises(RuntimeError, match="expected 384"):
        _ = emb.embedding_dim
