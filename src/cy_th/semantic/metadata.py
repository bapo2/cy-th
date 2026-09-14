# cy_th/semantic/metadata.py

"""Serialize / load `metadata.json` for published semantic indexes."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json

from cy_th.semantic.paths import metadata_path
from cy_th.semantic.types import SemanticMetadata


# === IO ===

def write_metadata(semantic_root: Path, meta: SemanticMetadata) -> Path:
    """Write `metadata.json` under `semantic_root`; returns the file path."""

    path = metadata_path(semantic_root)
    path.write_text(
        json.dumps(_to_json(meta), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path

def read_metadata(semantic_root: Path) -> SemanticMetadata:
    """Load and parse `metadata.json` from a semantic directory."""

    path = metadata_path(semantic_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("metadata.json must be a JSON object")
    return _from_json(raw)


# === Helpers ===

def _to_json(meta: SemanticMetadata) -> dict[str, object]:
    return {
        "run_id": meta.run_id,
        "model_id": meta.model_id,
        "model_revision": meta.model_revision,
        "embedding_dim": meta.embedding_dim,
        "normalize": meta.normalize,
        "metric": meta.metric,
        "document_count": meta.document_count,
        "text_budget": meta.text_budget,
        "sentence_transformers_version": meta.sentence_transformers_version,
        "built_at": meta.built_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }

def _from_json(raw: dict[str, object]) -> SemanticMetadata:
    built_raw = raw.get("built_at")
    if not isinstance(built_raw, str):
        raise ValueError("metadata.built_at must be an ISO-8601 UTC string")
    built_at = datetime.fromisoformat(built_raw.replace("Z", "+00:00"))
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=timezone.utc)

    def req_str(key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str):
            raise ValueError(f"metadata.{key} must be a string")
        return value

    def opt_str(key: str) -> str | None:
        value = raw.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"metadata.{key} must be a string or null")
        return value

    def req_int(key: str) -> int:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"metadata.{key} must be an int")
        return value

    def req_bool(key: str) -> bool:
        value = raw.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"metadata.{key} must be a bool")
        return value

    return SemanticMetadata(
        run_id=req_str("run_id"),
        model_id=req_str("model_id"),
        model_revision=opt_str("model_revision"),
        embedding_dim=req_int("embedding_dim"),
        normalize=req_bool("normalize"),
        metric=req_str("metric"),
        document_count=req_int("document_count"),
        text_budget=req_int("text_budget"),
        sentence_transformers_version=opt_str("sentence_transformers_version"),
        built_at=built_at,
    )
