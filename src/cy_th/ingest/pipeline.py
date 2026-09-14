# cy_th/ingest/pipeline.py

"""Acquire projected prime-transaction shards, then optionally materialize."""

# === Imports ===

from __future__ import annotations
from datetime import date
from pathlib import Path

from cy_th.ingest.client import UsaSpendingClient
from cy_th.ingest.errors import InvalidIngestRequestError
from cy_th.ingest.manifest import (
    load_planned_shards,
    new_job_document,
    read_json,
    shard_is_complete,
    shard_manifest,
    utc_now_iso,
    write_json_atomic,
)
from cy_th.ingest.paths import (
    job_dir,
    job_id as make_job_id,
    job_manifest_path,
    shard_csv_path,
    shard_manifest_path,
    shards_dir,
)
from cy_th.ingest.planner import plan_shards
from cy_th.ingest.types import (
    DateWindow,
    DownloadClient,
    IngestResult,
    JobStatus,
    PlannedShard,
)
from cy_th.materialize.paths import resolve_data_root
from cy_th.materialize.pipeline import materialize


# === Pipeline ===

def ingest(
    *,
    from_date: date,
    to_date: date,
    out: Path | str | None = None,
    materialize_set: bool = True,
    client: DownloadClient | None = None,
    allow_rejects: bool = False,
    keep_staging: bool = False,
) -> IngestResult:
    """Plan / resume / download shards under `out/ingest/<job-id>/`, then materialize.

    Completed shards (CSV + matching checksum manifest) are skipped. Compact mode discards the download zip after extract (handled in the client).
    """

    if to_date < from_date:
        raise InvalidIngestRequestError(
            f"--to {to_date.isoformat()} precedes --from {from_date.isoformat()}"
        )

    data_root = resolve_data_root(out)
    jid = make_job_id(from_date=from_date, to_date=to_date)
    job_path = job_dir(data_root, jid)
    shards_dir(job_path).mkdir(parents=True, exist_ok=True)

    resolved_client = client if client is not None else UsaSpendingClient()
    request_window = DateWindow(start=from_date, end=to_date)

    job_file = job_manifest_path(job_path)
    shards, job_doc = _load_or_plan(
        job_file,
        job_id=jid,
        window=request_window,
        client=resolved_client,
    )

    downloaded = 0
    skipped = 0
    csv_paths: list[Path] = []
    _set_job_status(job_file, job_doc, JobStatus.DOWNLOADING)

    for planned in shards:
        csv_path = shard_csv_path(job_path, planned.window)
        man_path = shard_manifest_path(job_path, planned.window)
        if shard_is_complete(csv_path, man_path):
            skipped += 1
            csv_paths.append(csv_path)
            continue

        _clear_incomplete(csv_path, man_path)
        result = resolved_client.download_transactions(planned.window, csv_path)
        write_json_atomic(
            man_path,
            shard_manifest(planned.window, csv_path=csv_path, download=result),
        )
        downloaded += 1
        csv_paths.append(csv_path)

    csv_tuple = tuple(csv_paths)
    _set_job_status(job_file, job_doc, JobStatus.ACQUIRED)

    run_id: str | None = None
    status = JobStatus.ACQUIRED
    if materialize_set:
        if not csv_tuple:
            raise InvalidIngestRequestError(
                f"no transactions in {from_date.isoformat()}..{to_date.isoformat()} to materialize"
            )
        published = materialize(
            csv_tuple,
            out=data_root,
            allow_rejects=allow_rejects,
            keep_staging=keep_staging,
        )
        run_id = published.run_id
        status = JobStatus.MATERIALIZED
        _set_job_status(job_file, job_doc, status, run_id=run_id)

    return IngestResult(
        job_id=jid,
        data_root=data_root,
        job_dir=job_path,
        from_date=from_date,
        to_date=to_date,
        shards=shards,
        csv_paths=csv_tuple,
        downloaded=downloaded,
        skipped_complete=skipped,
        status=status,
        run_id=run_id,
    )


# === Job Plan Persistence ===

def _load_or_plan(
    job_file: Path,
    *,
    job_id: str,
    window: DateWindow,
    client: DownloadClient,
) -> tuple[tuple[PlannedShard, ...], dict[str, object]]:
    if job_file.is_file():
        doc = read_json(job_file)
        existing = load_planned_shards(doc)
        if existing:
            return existing, doc

    planned = plan_shards(window, client)
    doc = new_job_document(
        job_id=job_id,
        from_date=window.start.isoformat(),
        to_date=window.end.isoformat(),
        shards=planned,
    )
    write_json_atomic(job_file, doc)
    return planned, doc

def _set_job_status(
    job_file: Path,
    doc: dict[str, object],
    status: JobStatus,
    *,
    run_id: str | None = None,
) -> None:
    doc["status"] = status.value
    doc["updated_at"] = utc_now_iso()
    if run_id is not None:
        doc["run_id"] = run_id
    write_json_atomic(job_file, doc)

def _clear_incomplete(csv_path: Path, manifest_path: Path) -> None:
    if csv_path.exists():
        csv_path.unlink()
    if manifest_path.exists():
        manifest_path.unlink()
