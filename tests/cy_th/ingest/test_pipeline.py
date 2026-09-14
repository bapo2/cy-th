# tests/cy_th/ingest/test_pipeline.py

"""Ingest job layout, resume, and materialize handoff (`FakeDownloadClient`)."""

# === Imports ===

from __future__ import annotations
from datetime import date
from pathlib import Path
import pytest

from cy_th.ingest.errors import InvalidIngestRequestError
from cy_th.ingest.fake import FakeDownloadClient
from cy_th.ingest.manifest import read_json, shard_is_complete
from cy_th.ingest.paths import job_id, job_manifest_path, shard_csv_path, shard_manifest_path
from cy_th.ingest.pipeline import ingest
from cy_th.ingest.types import DateWindow, JobStatus
from cy_th.materialize.paths import read_current
from tests.factories.projected_csv import blank_projected_row


# === Helpers ===

def _row(txn: str, award: str, day: str) -> dict[str, str]:
    return blank_projected_row(
        contract_transaction_unique_key=txn,
        contract_award_unique_key=award,
        action_date=day,
        federal_action_obligation="10.00",
        recipient_uei="UEI_ALPHA",
        awarding_agency_code="097",
        awarding_sub_agency_code="1700",
        awarding_office_code="N00024",
        funding_agency_code="097",
        funding_sub_agency_code="1700",
        funding_office_code="N00024",
        naics_code="541330",
        product_or_service_code="R425",
    )


# === Identity / Validation ===

def test_job_id_is_stable() -> None:
    a = job_id(from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))
    b = job_id(from_date=date(2025, 1, 1), to_date=date(2025, 1, 31))
    c = job_id(from_date=date(2025, 1, 1), to_date=date(2025, 2, 1))
    assert a == b
    assert a != c
    assert a.startswith("2025-01-01_2025-01-31_")

def test_from_after_to_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidIngestRequestError, match="precedes"):
        ingest(
            from_date=date(2025, 2, 1),
            to_date=date(2025, 1, 1),
            out=tmp_path,
            materialize_set=False,
            client=FakeDownloadClient(),
        )


# === Acquire ===

def test_ingest_writes_job_and_shard_manifests(tmp_path: Path) -> None:
    window = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 10))
    client = FakeDownloadClient(
        counts={window.shard_id: 1},
        csv_rows={window.shard_id: [_row("T1", "A1", "2025-01-10")]},
    )
    result = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    assert result.status is JobStatus.ACQUIRED
    assert result.downloaded == 1
    assert result.skipped_complete == 0
    assert (result.job_dir / "job.json").is_file()
    csv_path = shard_csv_path(result.job_dir, window)
    man_path = shard_manifest_path(result.job_dir, window)
    assert shard_is_complete(csv_path, man_path)
    shard_doc = read_json(man_path)
    assert shard_doc["row_count"] == 1
    assert shard_doc["filters"]["time_period"][0]["date_type"] == "action_date"

def test_resume_skips_complete_shards(tmp_path: Path) -> None:
    window = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 10))
    client = FakeDownloadClient(
        counts={window.shard_id: 1},
        csv_rows={window.shard_id: [_row("T1", "A1", "2025-01-10")]},
    )
    first = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    assert first.downloaded == 1
    second = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    assert second.job_id == first.job_id
    assert second.downloaded == 0
    assert second.skipped_complete == 1
    assert client.download_calls == [window.shard_id]

def test_ingest_materializes_current(tmp_path: Path) -> None:
    window = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 10))
    client = FakeDownloadClient(
        counts={window.shard_id: 1},
        csv_rows={window.shard_id: [_row("T1", "A1", "2025-01-10")]},
    )
    result = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=True,
        client=client,
    )
    assert result.status is JobStatus.MATERIALIZED
    assert result.run_id is not None
    assert read_current(tmp_path) == result.run_id
    job_doc = read_json(job_manifest_path(result.job_dir))
    assert job_doc["run_id"] == result.run_id
    assert job_doc["status"] == "materialized"


# === Materialize / Download ===

def test_empty_interval_cannot_materialize(tmp_path: Path) -> None:
    client = FakeDownloadClient(rows_per_day=0)
    with pytest.raises(InvalidIngestRequestError, match="no transactions"):
        ingest(
            from_date=date(2025, 1, 1),
            to_date=date(2025, 1, 2),
            out=tmp_path,
            materialize_set=True,
            client=client,
        )

def test_incomplete_shard_is_redownloaded(tmp_path: Path) -> None:
    window = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 10))
    client = FakeDownloadClient(
        counts={window.shard_id: 1},
        csv_rows={window.shard_id: [_row("T1", "A1", "2025-01-10")]},
    )
    first = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    csv_path = shard_csv_path(first.job_dir, window)
    csv_path.write_text("truncated", encoding="utf-8")
    second = ingest(
        from_date=window.start,
        to_date=window.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    assert second.downloaded == 1
    assert client.download_calls == [window.shard_id, window.shard_id]

def test_download_job_failure_bisects_shard(tmp_path: Path) -> None:
    full = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 11))
    left = DateWindow(start=date(2025, 1, 10), end=date(2025, 1, 10))
    right = DateWindow(start=date(2025, 1, 11), end=date(2025, 1, 11))
    client = FakeDownloadClient(
        counts={
            full.shard_id: 2,
            left.shard_id: 1,
            right.shard_id: 1,
        },
        csv_rows={
            left.shard_id: [_row("T1", "A1", "2025-01-10")],
            right.shard_id: [_row("T2", "A2", "2025-01-11")],
        },
        fail_download_ids={full.shard_id},
    )
    result = ingest(
        from_date=full.start,
        to_date=full.end,
        out=tmp_path,
        materialize_set=False,
        client=client,
    )
    assert result.downloaded == 2
    assert [s.window.shard_id for s in result.shards] == [left.shard_id, right.shard_id]
    assert shard_is_complete(
        shard_csv_path(result.job_dir, left),
        shard_manifest_path(result.job_dir, left),
    )
    assert shard_is_complete(
        shard_csv_path(result.job_dir, right),
        shard_manifest_path(result.job_dir, right),
    )
