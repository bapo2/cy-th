# tests/cy_th/agent/conftest.py

"""Fixtures for procurement-agent offline tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest


# === Fixtures ===

@pytest.fixture
def agent_root(query_data_root: Path) -> Path:
    """Published data root for agent tests (shared query fixture)."""

    return query_data_root
