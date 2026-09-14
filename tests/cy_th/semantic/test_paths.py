# tests/cy_th/semantic/test_paths.py

"""Semantic path helper tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.semantic.paths import (
    derived_run_dir,
    documents_path,
    embeddings_path,
    metadata_path,
    semantic_dir,
    semantic_staging_dir,
)


# === Layout / Paths ===

def test_semantic_layout_helpers(tmp_path: Path) -> None:
    run_id = "20260914T190000Z_abcdef"
    assert derived_run_dir(tmp_path, run_id) == tmp_path / "derived" / run_id
    assert semantic_dir(tmp_path, run_id) == tmp_path / "derived" / run_id / "semantic"
    assert (
        semantic_staging_dir(tmp_path, run_id)
        == tmp_path / "derived" / run_id / ".tmp-semantic"
    )
    root = semantic_dir(tmp_path, run_id)
    assert documents_path(root).name == "documents.parquet"
    assert embeddings_path(root).name == "embeddings.npy"
    assert metadata_path(root).name == "metadata.json"

def test_invalid_run_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid run_id"):
        derived_run_dir(tmp_path, "not-a-run-id")
