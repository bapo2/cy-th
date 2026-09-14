# tests/cy_th/semantic/test_semantic_model.py

"""Optional real-model smoke (opt-in via `-m semantic_model`)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.semantic.build import build_semantic_index
from cy_th.semantic.index import SemanticIndex
from cy_th.semantic.paths import DEFAULT_MODEL_ID, QUERY_PREFIX


# === Real Model ===

@pytest.mark.semantic_model
def test_real_bge_build_and_rank(semantic_data_root: Path) -> None:
    """Tiny end-to-end check with cached BGE weights (skipped unless marker selected)."""

    pytest.importorskip("sentence_transformers")
    from cy_th.semantic.embed import SentenceTransformerEmbedder

    try:
        embedder = SentenceTransformerEmbedder(DEFAULT_MODEL_ID, local_files_only=True)
        _ = embedder.embedding_dim
    except Exception as exc:
        pytest.skip(f"cached BGE weights unavailable: {exc}")
    with ProcurementDataset.open(semantic_data_root) as ds:
        build_semantic_index(ds, embedder, force=True, batch_size=8)
        with SemanticIndex.open(ds, embedder) as index:
            assert index.metadata.query_prefix == QUERY_PREFIX
            radar = index.search("detection and surveillance systems", top_k=1)
            food = index.search("food catering and meals", top_k=1)
            assert radar.hits[0].award_id == "A_RADAR"
            assert food.hits[0].award_id == "A_FOOD"
