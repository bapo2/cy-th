# tests/cy_th/semantic/test_metadata.py

"""metadata.json serialize / load edge cases."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import pytest

from cy_th.semantic.metadata import read_metadata, write_metadata
from cy_th.semantic.paths import QUERY_PREFIX
from cy_th.semantic.types import SemanticMetadata


# === Round-Trip ===

def test_metadata_round_trip(tmp_path: Path) -> None:
    meta = SemanticMetadata(
        run_id="20260914T190000Z_abcdef",
        model_id="fake/deterministic-v1",
        model_revision="test",
        embedding_dim=384,
        normalize=True,
        metric="cosine",
        query_prefix=QUERY_PREFIX,
        document_count=3,
        text_budget=1800,
        sentence_transformers_version=None,
        built_at=datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc),
    )
    write_metadata(tmp_path, meta)
    loaded = read_metadata(tmp_path)
    assert loaded.run_id == meta.run_id
    assert loaded.query_prefix == QUERY_PREFIX
    assert loaded.model_revision == "test"
    assert loaded.sentence_transformers_version is None
    assert loaded.built_at == meta.built_at


# === Validation ===

def test_read_metadata_rejects_bad_shapes(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"

    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        read_metadata(tmp_path)

    path.write_text(json.dumps({"built_at": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="built_at"):
        read_metadata(tmp_path)

    path.write_text(
        json.dumps({"built_at": "2026-09-14T12:00:00Z", "run_id": 1}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="run_id"):
        read_metadata(tmp_path)

    path.write_text(
        json.dumps(
            {
                "built_at": "2026-09-14T12:00:00",
                "run_id": "r",
                "model_id": "m",
                "model_revision": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="model_revision"):
        read_metadata(tmp_path)

    path.write_text(
        json.dumps(
            {
                "built_at": "2026-09-14T12:00:00Z",
                "run_id": "r",
                "model_id": "m",
                "model_revision": None,
                "embedding_dim": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="embedding_dim"):
        read_metadata(tmp_path)

    path.write_text(
        json.dumps(
            {
                "built_at": "2026-09-14T12:00:00Z",
                "run_id": "r",
                "model_id": "m",
                "model_revision": None,
                "embedding_dim": 384,
                "normalize": "yes",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="normalize"):
        read_metadata(tmp_path)
