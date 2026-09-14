# cy_th/ingest/paths.py

"""On-disk layout for ingest jobs (`<data-root>/ingest/<job-id>/`)."""

# === Imports ===

from __future__ import annotations
import hashlib
from datetime import date
from pathlib import Path
from typing import Final

from cy_th.ingest.types import DateWindow
from cy_th.materialize.paths import resolve_data_root
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Constants ===

INGEST_DIRNAME: Final[str] = "ingest"
SHARDS_DIRNAME: Final[str] = "shards"
JOB_FILENAME: Final[str] = "job.json"
INGEST_VERSION: Final[str] = "1"
"""Control-plane schema version recorded on job + shard manifests."""

POPULATION_KEY: Final[str] = "dod-awarding-toptier|ABCD"


# === Job Identity ===

def job_id(*, from_date: date, to_date: date) -> str:
    """Deterministic job id from extraction parameters (resume-stable).

    #### Form:
        `{from}_{to}_{12-hex}` where the digest covers population, interval, projection, and ingest version
    """

    payload = "|".join(
        (
            POPULATION_KEY,
            from_date.isoformat(),
            to_date.isoformat(),
            INGEST_VERSION,
            ",".join(TRANSACTION_DOWNLOAD_COLUMNS),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{from_date.isoformat()}_{to_date.isoformat()}_{digest}"


# === Roots ===

def ingest_root(data_root: Path | str | None = None) -> Path:
    """`<data-root>/ingest/`."""

    return resolve_data_root(data_root) / INGEST_DIRNAME

def job_dir(data_root: Path | str | None, job: str) -> Path:
    """`<data-root>/ingest/<job-id>/`."""

    return ingest_root(data_root) / job

def shards_dir(job_path: Path) -> Path:
    """`<job>/shards/`."""

    return job_path / SHARDS_DIRNAME

def job_manifest_path(job_path: Path) -> Path:
    return job_path / JOB_FILENAME

def shard_csv_path(job_path: Path, window: DateWindow) -> Path:
    return shards_dir(job_path) / f"{window.shard_id}.csv"

def shard_manifest_path(job_path: Path, window: DateWindow) -> Path:
    return shards_dir(job_path) / f"{window.shard_id}.json"
