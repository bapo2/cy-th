# cy_th/enrichment/paths.py

"""On-disk layout for enrichment cache (`<data-root>/enrichment/`)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
from typing import Final
from urllib.parse import quote

from cy_th.materialize.paths import resolve_data_root


# === Constants ===

ENRICHMENT_DIRNAME: Final[str] = "enrichment"
AWARDS_DIRNAME: Final[str] = "awards"
IDVS_DIRNAME: Final[str] = "idvs"
ENRICHMENT_VERSION: Final[str] = "1"
"""Control-plane schema version recorded on cache documents."""


# === Roots ===

def enrichment_root(data_root: Path | str | None = None) -> Path:
    """`<data-root>/enrichment/`."""

    return resolve_data_root(data_root) / ENRICHMENT_DIRNAME

def awards_cache_dir(data_root: Path | str | None = None) -> Path:
    return enrichment_root(data_root) / AWARDS_DIRNAME

def idvs_cache_dir(data_root: Path | str | None = None) -> Path:
    return enrichment_root(data_root) / IDVS_DIRNAME


# === File Paths ===

def award_cache_path(data_root: Path | str | None, award_id: str) -> Path:
    return awards_cache_dir(data_root) / f"{_safe_id(award_id)}.json"

def idv_cache_path(data_root: Path | str | None, idv_id: str) -> Path:
    return idvs_cache_dir(data_root) / f"{_safe_id(idv_id)}.json"


# === Helpers ===

def _safe_id(identity: str) -> str:
    """URL-safe filename fragment for a USASpending generated id."""

    return quote(identity.strip(), safe="")
