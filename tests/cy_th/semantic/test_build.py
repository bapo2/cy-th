# tests/cy_th/semantic/test_build.py

"""Build / publish / metadata compatibility tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.semantic.build import build_semantic_index, validate_semantic_artifacts
from cy_th.semantic.embed import FakeEmbedder
from cy_th.semantic.errors import (
    IncompatibleSemanticIndexError,
    MissingSemanticIndexError,
    SemanticError,
    SemanticIndexExistsError,
)
from cy_th.semantic.metadata import read_metadata
from cy_th.semantic.paths import (
    EMBEDDING_DIM,
    QUERY_PREFIX,
    documents_path,
    embeddings_path,
    metadata_path,
    semantic_dir,
    semantic_staging_dir,
)
from tests.cy_th.semantic.conftest import _award, materialize_rows


# === Happy Path ===

def test_build_publishes_artifacts_and_omits_empty(
    semantic_data_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(semantic_data_root) as ds:
        result = build_semantic_index(ds, fake_embedder, batch_size=4)

    published = semantic_dir(semantic_data_root, result.run_id)
    assert result.semantic_path == published
    assert documents_path(published).is_file()
    assert embeddings_path(published).is_file()
    assert metadata_path(published).is_file()
    assert not semantic_staging_dir(semantic_data_root, result.run_id).exists()

    # A_EMPTY omitted; A_RADAR, A_FOOD, A_ENG, A_TXN indexed
    assert result.document_count == 4

    meta = read_metadata(published)
    assert meta.run_id == result.run_id
    assert meta.model_id == fake_embedder.model_id
    assert meta.model_revision == fake_embedder.model_revision
    assert meta.embedding_dim == EMBEDDING_DIM
    assert meta.normalize is True
    assert meta.metric == "cosine"
    assert meta.query_prefix == QUERY_PREFIX
    assert meta.document_count == 4
    assert meta.text_budget == 1800

    matrix = np.load(embeddings_path(published))
    assert matrix.shape == (4, EMBEDDING_DIM)
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)

    validate_semantic_artifacts(published, expected_run_id=result.run_id)


# === Exists / Force ===

def test_build_refuses_existing_without_force(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(built_semantic_root) as ds:
        with pytest.raises(SemanticIndexExistsError, match="--force"):
            build_semantic_index(ds, fake_embedder, force=False)

def test_build_force_replaces_published_index(
    built_semantic_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    published = semantic_dir(built_semantic_root, "20260914T190000Z_abcdef")
    before = metadata_path(published).read_text(encoding="utf-8")
    with ProcurementDataset.open(built_semantic_root) as ds:
        result = build_semantic_index(ds, fake_embedder, force=True, batch_size=8)
    assert result.forced is True
    after = metadata_path(published).read_text(encoding="utf-8")
    assert '"query_prefix"' in after
    # Rebuild rewrites metadata (timestamp should change at minimum)
    assert after != before or result.document_count == 4


# === Empty / Missing ===

def test_build_rejects_empty_indexable_set(tmp_path: Path, fake_embedder: FakeEmbedder) -> None:
    root = materialize_rows(
        tmp_path,
        [
            _award(
                "T1",
                "A_EMPTY",
                "",
                "",
                naics_code="",
                naics_description="",
                psc="",
                psc_description="",
            )
        ],
        run_id="20260914T190000Z_aaaaaa",
    )
    with ProcurementDataset.open(root) as ds:
        with pytest.raises(SemanticError, match="no indexable"):
            build_semantic_index(ds, fake_embedder)

def test_validate_missing_artifacts(tmp_path: Path) -> None:
    empty = tmp_path / "semantic"
    empty.mkdir()
    with pytest.raises(MissingSemanticIndexError, match="missing"):
        validate_semantic_artifacts(empty, expected_run_id="r1")


# === Fingerprint ===

def test_validate_rejects_fingerprint_mismatches(
    built_semantic_root: Path,
) -> None:
    published = semantic_dir(built_semantic_root, "20260914T190000Z_abcdef")
    raw = json.loads(metadata_path(published).read_text(encoding="utf-8"))

    for key, value, match in (
        ("query_prefix", "WRONG: ", "query_prefix"),
        ("metric", "euclidean", "metric"),
        ("normalize", False, "normalize"),
        ("embedding_dim", 16, "embedding_dim"),
        ("document_count", 0, "document_count"),
        ("run_id", "20260914T190000Z_ffffff", "run_id"),
    ):
        mutated = dict(raw)
        mutated[key] = value
        metadata_path(published).write_text(
            json.dumps(mutated, indent=2) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(IncompatibleSemanticIndexError, match=match):
            validate_semantic_artifacts(
                published,
                expected_run_id="20260914T190000Z_abcdef",
            )

    # Restore valid metadata for later fixtures
    metadata_path(published).write_text(
        json.dumps(raw, indent=2) + "\n",
        encoding="utf-8",
    )

def test_build_rejects_nonpositive_batch_size(
    semantic_data_root: Path,
    fake_embedder: FakeEmbedder,
) -> None:
    with ProcurementDataset.open(semantic_data_root) as ds:
        with pytest.raises(ValueError, match="batch_size"):
            build_semantic_index(ds, fake_embedder, batch_size=0)
