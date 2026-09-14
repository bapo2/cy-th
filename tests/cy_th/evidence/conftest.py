# tests/cy_th/evidence/conftest.py

"""Fixtures for evidence-session tests (reuse query materialization)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.semantic.build import build_semantic_index
from cy_th.semantic.embed import FakeEmbedder


# === Fixtures ===

# Reuse the shared multi-award published set from query tests
pytest_plugins = ["tests.cy_th.query.conftest"]

@pytest.fixture
def evidence_root(query_data_root: Path) -> Path:
    """Published data root for evidence tests (alias of the query fixture)."""

    return query_data_root

@pytest.fixture
def evidence_root_with_semantic(evidence_root: Path) -> Path:
    """Published data root plus a `FakeEmbedder` semantic index."""

    with ProcurementDataset.open(evidence_root) as ds:
        build_semantic_index(ds, FakeEmbedder(), force=True, batch_size=8)
    return evidence_root
