# cy_th/ingest/manifest.py

"""Job + per-shard ingestion manifests (control plane)."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json

from cy_th.ingest.filters import (
    API_BASE,
    AWARD_TYPE_CODES,
    AWARDING_AGENCY_NAME,
    ENDPOINT_TRANSACTIONS,
    population_filters,
)
from cy_th.ingest.paths import INGEST_VERSION
from cy_th.ingest.types import DateWindow, DownloadResult, JobStatus, PlannedShard
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Checksums ===

def sha256_file(path: Path) -> str:
    """Hex SHA-256 of `path` (chunked)."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# === JSON IO ===

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# === Job Manifest ===

def new_job_document(
    *,
    job_id: str,
    from_date: str,
    to_date: str,
    shards: tuple[PlannedShard, ...],
    status: JobStatus = JobStatus.PLANNED,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "ingest_version": INGEST_VERSION,
        "source": API_BASE,
        "endpoint": ENDPOINT_TRANSACTIONS,
        "from_date": from_date,
        "to_date": to_date,
        "status": status.value,
        "shards": [shard.to_dict() for shard in shards],
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "run_id": None,
    }

def load_planned_shards(job_doc: Mapping[str, Any]) -> tuple[PlannedShard, ...]:
    raw = job_doc.get("shards") or []
    if not isinstance(raw, list):
        raise ValueError("job manifest shards must be a list")
    return tuple(PlannedShard.from_dict(item) for item in raw)


# === Shard Manifest ===

def shard_manifest(
    window: DateWindow,
    *,
    csv_path: Path,
    download: DownloadResult,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    checksum = sha256_file(csv_path)
    return {
        "ingest_version": INGEST_VERSION,
        "source": API_BASE,
        "endpoint": ENDPOINT_TRANSACTIONS,
        "filters": population_filters(window),
        "from_date": window.start.isoformat(),
        "to_date": window.end.isoformat(),
        "field_projection": list(TRANSACTION_DOWNLOAD_COLUMNS),
        "award_type_codes": list(AWARD_TYPE_CODES),
        "awarding_agency": AWARDING_AGENCY_NAME,
        "retrieval_time": retrieved_at if retrieved_at is not None else utc_now_iso(),
        "row_count": download.row_count,
        "bytes": download.bytes_written,
        "source_file_name": download.source_file_name,
        "checksum_sha256": checksum,
        "status": "complete",
        "csv": csv_path.name,
    }

def shard_is_complete(csv_path: Path, manifest_path: Path) -> bool:
    """True when CSV + complete manifest exist and checksum matches."""

    if not csv_path.is_file() or csv_path.stat().st_size <= 0:
        return False
    if not manifest_path.is_file():
        return False
    try:
        doc = read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return False
    if doc.get("status") != "complete":
        return False
    expected = doc.get("checksum_sha256")
    if not isinstance(expected, str) or not expected:
        return False
    return sha256_file(csv_path) == expected


# === Time ===

def utc_now_iso() -> str:
    """UTC timestamp `YYYY-MM-DDTHH:MM:SSZ`."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
