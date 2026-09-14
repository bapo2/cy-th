# tests/cy_th/ingest/test_planner.py

"""Date-window bisection for USASpending download caps."""

# === Imports ===

from __future__ import annotations
from datetime import date
import pytest

from cy_th.ingest.errors import ShardTooLargeError, TransientUsaSpendingError
from cy_th.ingest.fake import FakeDownloadClient
from cy_th.ingest.filters import count_request_body, download_request_body
from cy_th.ingest.planner import plan_shards
from cy_th.ingest.types import DateWindow


# === Helpers ===

JAN = DateWindow(start=date(2025, 1, 1), end=date(2025, 1, 4))


# === Plan ===

def test_under_cap_is_one_shard() -> None:
    client = FakeDownloadClient(rows_per_day=10)
    planned = plan_shards(JAN, client, cap=100)
    assert len(planned) == 1
    assert planned[0].window == JAN
    assert planned[0].planned_count == 40

def test_bisect_until_under_cap() -> None:
    # 4 days * 30 = 120; cap 50 → split until each window's count <= 50
    client = FakeDownloadClient(rows_per_day=30)
    planned = plan_shards(JAN, client, cap=50)
    assert planned
    assert all(shard.planned_count <= 50 for shard in planned)
    days = []
    for shard in planned:
        assert shard.window.start <= shard.window.end
        cursor = shard.window.start
        while cursor <= shard.window.end:
            days.append(cursor)
            if cursor == shard.window.end:
                break
            cursor = date.fromordinal(cursor.toordinal() + 1)
    assert days == [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 4),
    ]

def test_empty_windows_omitted() -> None:
    client = FakeDownloadClient(
        counts={
            "2025-01-01_2025-01-04": 80,
            "2025-01-01_2025-01-02": 0,
            "2025-01-03_2025-01-04": 40,
        },
        rows_per_day=0,
    )
    planned = plan_shards(JAN, client, cap=50)
    assert [s.window.shard_id for s in planned] == ["2025-01-03_2025-01-04"]

def test_single_day_over_cap_fails() -> None:
    day = DateWindow(start=date(2025, 1, 1), end=date(2025, 1, 1))
    client = FakeDownloadClient(counts={"2025-01-01_2025-01-01": 900_000})
    with pytest.raises(ShardTooLargeError, match="2025-01-01"):
        plan_shards(day, client, cap=500_000)

def test_count_timeout_bisects_until_countable() -> None:
    # Full 4-day window times out; halves that are <= 2 days succeed under cap.
    client = FakeDownloadClient(rows_per_day=10, timeout_when_days_gt=2)
    planned = plan_shards(JAN, client, cap=100)
    assert planned
    assert all(shard.planned_count <= 100 for shard in planned)
    assert all((s.window.end - s.window.start).days + 1 <= 2 for s in planned)
    assert any("2025-01-01_2025-01-04" in call for call in client.count_calls)

def test_single_day_count_timeout_fails() -> None:
    day = DateWindow(start=date(2025, 1, 1), end=date(2025, 1, 1))
    client = FakeDownloadClient(timeout_when_days_gt=0)
    with pytest.raises(TransientUsaSpendingError):
        plan_shards(day, client, cap=500_000)

def test_request_bodies_lock_population() -> None:
    window = DateWindow(start=date(2025, 1, 1), end=date(2025, 1, 2))
    count = count_request_body(window)
    download = download_request_body(window)
    assert count["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert download["filters"]["agencies"][0]["name"] == "Department of Defense"
    assert download["columns"]
