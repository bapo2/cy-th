# cy_th/ingest/planner.py

"""Bisect an `action_date` interval until each shard is under the download cap."""

# === Imports ===

from __future__ import annotations
from collections import deque
from datetime import timedelta
import sys

from cy_th.ingest.errors import ShardTooLargeError, TransientUsaSpendingError
from cy_th.ingest.filters import DOWNLOAD_ROW_CAP
from cy_th.ingest.types import DateWindow, DownloadClient, PlannedShard


# === Plan ===

def plan_shards(
    window: DateWindow,
    client: DownloadClient,
    *,
    cap: int = DOWNLOAD_ROW_CAP,
) -> tuple[PlannedShard, ...]:
    """Return downloadable windows covering `window` (empty counts omitted).

    Bisects over-limit intervals at the date midpoint. A single day still over `cap` raises `ShardTooLargeError`.

    Large windows will 504 on `/download/count/`; after retries the client raises `TransientUsaSpendingError`, which is treated like "over cap" and bisected until counts succeed (or a single day still fails).
    """

    if cap <= 0:
        raise ValueError(f"cap must be > 0, got {cap}")

    pending: deque[DateWindow] = deque([window])
    planned: list[PlannedShard] = []

    while pending:
        current = pending.popleft()
        try:
            count = client.count_transactions(current)
        except TransientUsaSpendingError as exc:
            if current.start == current.end:
                raise
            print(
                f"USASpending count timed out for {current.shard_id}; bisecting "
                f"({exc.status_code or 'transient'})",
                file=sys.stderr,
                flush=True,
            )
            _enqueue_halves(pending, current)
            continue

        if count < 0:
            raise ValueError(f"count must be >= 0, got {count} for {current.shard_id}")
        if count == 0:
            continue
        if count <= cap:
            planned.append(PlannedShard(window=current, planned_count=count))
            continue
        if current.start == current.end:
            raise ShardTooLargeError(day=current.start, count=count, cap=cap)

        _enqueue_halves(pending, current)

    planned.sort(key=lambda shard: (shard.window.start, shard.window.end))
    return tuple(planned)


# === Helpers ===

def _enqueue_halves(pending: deque[DateWindow], current: DateWindow) -> None:
    span_days = (current.end - current.start).days
    mid = current.start + timedelta(days=span_days // 2)
    left = DateWindow(start=current.start, end=mid)
    right = DateWindow(start=mid + timedelta(days=1), end=current.end)
    pending.appendleft(right)
    pending.appendleft(left)
