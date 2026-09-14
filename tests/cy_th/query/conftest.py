# tests/cy_th/query/conftest.py

"""Shared fixtures for procurement query runtime tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.query.dataset import ProcurementDataset


# === Dataset Fixture ===

@pytest.fixture
def dataset(query_data_root: Path) -> ProcurementDataset:
    """Open the synthetic query fixture (close via context or explicit `close`)."""

    return ProcurementDataset.open(query_data_root)
