# cy_th/enrichment/cache.py

"""Read / write / evict enrichment JSON cache records."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json

from cy_th.enrichment.paths import ENRICHMENT_VERSION
from cy_th.enrichment.types import (
    AwardSelected,
    EnrichmentResource,
    IdvSelected,
)
from cy_th.ingest.filters import API_BASE


# === Endpoint ===

def award_detail_endpoint(source_id: str) -> str:
    """Absolute URL for `GET /awards/{id}/`."""

    return f"{API_BASE}/awards/{source_id}/"


# === Time ===

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# === JSON IO ===

def read_cache_doc(path: Path) -> dict[str, Any] | None:
    """Return a cache document, or `None` if missing / unreadable."""

    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc

def write_cache_doc(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(doc), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)

def evict_cache(path: Path) -> bool:
    """Delete `path` if present. Returns whether a file was removed."""

    if not path.is_file():
        return False
    path.unlink()
    return True


# === Document Builders ===

def new_award_cache_doc(
    *,
    award_id: str,
    payload: Mapping[str, Any],
    selected: AwardSelected,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    endpoint = award_detail_endpoint(award_id)
    return {
        "enrichment_version": ENRICHMENT_VERSION,
        "resource_type": EnrichmentResource.AWARD.value,
        "source_id": award_id,
        "endpoint": endpoint,
        "retrieved_at": retrieved_at if retrieved_at is not None else utc_now_iso(),
        "selected": selected.to_dict(),
        "payload": dict(payload),
    }

def new_idv_cache_doc(
    *,
    idv_id: str,
    payload: Mapping[str, Any],
    selected: IdvSelected,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    endpoint = award_detail_endpoint(idv_id)
    return {
        "enrichment_version": ENRICHMENT_VERSION,
        "resource_type": EnrichmentResource.IDV.value,
        "source_id": idv_id,
        "endpoint": endpoint,
        "retrieved_at": retrieved_at if retrieved_at is not None else utc_now_iso(),
        "selected": selected.to_dict(),
        "payload": dict(payload),
    }
