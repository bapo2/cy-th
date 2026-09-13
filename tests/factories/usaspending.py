# tests/factories/usaspending.py

"""Real USASpending prime-transaction extracts for tests.

Prefers a local cache under `tests/.cache/usaspending/`. When cold, materializes from a TEMP research CSV if available, otherwise downloads one DoD day via the public `/download/transactions/` API using `TRANSACTION_DOWNLOAD_COLUMNS`.
"""

# === Imports ===

from __future__ import annotations
import csv
import json
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Constants ===

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CACHE_DIR: Final[Path] = REPO_ROOT / "tests" / ".cache" / "usaspending"

DEFAULT_ACTION_DATE: Final[str] = "2025-09-15"  # Busy single day from earlier research pulls

API_BASE: Final[str] = "https://api.usaspending.gov/api/v2"
USER_AGENT: Final[str] = "Mozilla/5.0 (compatible; cy-th-tests/0.1)"


# === Public API ===

def ensure_prime_txn_csv(
    *,
    action_date: str = DEFAULT_ACTION_DATE,
    allow_network: bool = True,
) -> Path:
    """Return a projected prime-txn CSV path, downloading/materializing if needed.

    #### Resolution order:
        1. Large TEMP research extract → materialize into `tests/.cache/`
        2. Existing cache file
        3. Live USASpending download (only when `allow_network=True`)
    """

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"prime_txns_{action_date}.csv"
    temp_src = _find_temp_prime_csv()

    # Prefer a large TEMP research extract over a tiny/stale cache
    # NOTE: We don't client-filter by action_date, TEMP day pulls are already bounded (filename date is download time, not necessarily action_date)
    if temp_src is not None and (
        not cached.is_file() or cached.stat().st_size < 50_000
    ):
        _materialize_projected_csv(temp_src, cached)
        return cached

    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    if not allow_network:
        raise FileNotFoundError(
            f"no local USASpending extract available under --offline; expected cache at {cached} or a TEMP Contracts_PrimeTransactions_*.csv"
        )

    _download_projected_day(action_date=action_date, dest_csv=cached)
    return cached

def load_prime_txn_rows(
    path: Path | None = None,
    *,
    action_date: str = DEFAULT_ACTION_DATE,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Load prime transaction rows as string dicts (CSV-native)."""

    csv_path = path or ensure_prime_txn_csv(action_date=action_date)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(dict(row))
    return rows

def group_rows_by_award(
    rows: Iterable[Mapping[str, str]],
) -> dict[str, list[dict[str, str]]]:
    """Group CSV rows by `contract_award_unique_key`."""

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        award_id = (row.get("contract_award_unique_key") or "").strip()
        if not award_id:
            continue
        grouped[award_id].append(dict(row))
    return dict(grouped)

def snapshot_input_from_csv_row(row: Mapping[str, str]) -> dict[str, Any]:
    """Map a USASpending CSV row to `project_award_from_transactions` input keys."""

    return {
        "transaction_id": (row.get("contract_transaction_unique_key") or "").strip(),
        "action_date": row.get("action_date"),
        "transaction_number": row.get("transaction_number"),
        "total_dollars_obligated": row.get("total_dollars_obligated"),
        "current_total_value_of_award": row.get("current_total_value_of_award"),
        "potential_total_value_of_award": row.get("potential_total_value_of_award"),
    }

def find_award_groups(
    grouped: Mapping[str, list[dict[str, str]]],
    *,
    min_txns: int = 1,
) -> list[tuple[str, list[dict[str, str]]]]:
    """Return `(award_id, rows)` pairs with at least `min_txns` transactions."""

    return [
        (award_id, rows)
        for award_id, rows in grouped.items()
        if len(rows) >= min_txns
    ]


# === Cache Materialization ===

def _find_temp_prime_csv() -> Path | None:
    """Pick the best TEMP research extract (prefer large full-width day pulls)."""

    temp = Path(tempfile.gettempdir())
    preferred_dirs = (
        temp / "usa_txn_day",
        temp / "usa_matrix_txns",
        temp / "usa_dod_txn_sample",
    )
    hits: list[Path] = []
    for directory in preferred_dirs:
        hits.extend(directory.glob("**/Contracts_PrimeTransactions_*.csv"))
    if not hits:
        hits = list(temp.glob("usa_*/**/Contracts_PrimeTransactions_*.csv"))
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_size)  # Prefer the largest file (so smoke leftovers don't win on mtime)

def _materialize_projected_csv(
    source: Path,
    dest: Path,
    *,
    action_date: str | None = None,
) -> None:
    """Write a projected-column CSV from a (possibly full-width) source file."""

    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"no header in {source}")
        missing = [c for c in TRANSACTION_DOWNLOAD_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"source CSV missing projected columns: {missing}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=list(TRANSACTION_DOWNLOAD_COLUMNS))
            writer.writeheader()
            wrote = 0
            for row in reader:
                if action_date is not None:
                    row_date = (row.get("action_date") or "").strip()[:10]
                    if row_date != action_date:
                        continue
                writer.writerow({c: row.get(c, "") for c in TRANSACTION_DOWNLOAD_COLUMNS})
                wrote += 1
            if wrote == 0:
                raise ValueError(
                    f"no rows for action_date={action_date!r} in {source}"
                )


# === Live Download ===

def _download_projected_day(*, action_date: str, dest_csv: Path) -> None:
    """Download one DoD action_date day with the project column allowlist."""

    body = {
        "filters": {
            "agencies": [
                {
                    "type": "awarding",
                    "tier": "toptier",
                    "name": "Department of Defense",
                }
            ],
            "time_period": [
                {
                    "start_date": action_date,
                    "end_date": action_date,
                    "date_type": "action_date",
                }
            ],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "columns": list(TRANSACTION_DOWNLOAD_COLUMNS),
        "file_format": "csv",
    }
    
    try:
        response = _post_json("/download/transactions/", body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"download request failed: {exc.code} {detail}") from exc

    file_name = response.get("file_name")
    status_url = response.get("status_url") or (
        f"{API_BASE}/download/status/?file_name={file_name}"
    )
    if not file_name:
        raise RuntimeError(f"unexpected download response: {response}")

    file_url: str | None = None
    for _ in range(90):
        status = _get_json(status_url)
        state = str(status.get("status") or "").lower()
        file_url = status.get("file_url") or status.get("url")
        if file_url and state in {"finished", "ready", ""}:
            break
        if state in {"failed", "error"}:
            raise RuntimeError(f"download failed: {status}")
        time.sleep(2)
    if not file_url:
        raise TimeoutError(f"timed out waiting for download of {file_name}")

    zip_path = CACHE_DIR / (
        file_name if str(file_name).endswith(".zip") else f"{file_name}.zip"
    )
    _download_file(file_url, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        member = next(
            (
                name
                for name in zf.namelist()
                if "PrimeTransactions" in name and name.endswith(".csv")
            ),
            None,
        )
        if member is None:
            raise RuntimeError(f"no PrimeTransactions CSV in {zip_path}")
        dest_csv.parent.mkdir(parents=True, exist_ok=True)
        dest_csv.write_bytes(zf.read(member))

def _post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as out:
        out.write(resp.read())
