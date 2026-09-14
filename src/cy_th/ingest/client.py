# cy_th/ingest/client.py

"""USASpending HTTP client for transaction count + projected download."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
from typing import Any
import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile

from cy_th.ingest.errors import UsaSpendingApiError
from cy_th.ingest.filters import (
    API_BASE,
    ENDPOINT_COUNT,
    ENDPOINT_TRANSACTIONS,
    count_request_body,
    download_request_body,
)
from cy_th.ingest.types import DateWindow, DownloadResult
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Constants ===

USER_AGENT: str = "Mozilla/5.0 (compatible; cy-th-ingest/0.1)"
_POLL_SECONDS: float = 2.0
_POLL_ATTEMPTS: int = 300
_HTTP_RETRIES: int = 4


# === Client ===

class UsaSpendingClient:
    """Live `/download/count/` + `/download/transactions/` client."""

    def __init__(
        self,
        *,
        api_base: str = API_BASE,
        user_agent: str = USER_AGENT,
        timeout: float = 180.0,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout

    def count_transactions(self, window: DateWindow) -> int:
        payload = self._post_json(ENDPOINT_COUNT, count_request_body(window))
        for key in ("calculated_transaction_count", "calculated_count"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, float):
                return int(value)
        raise UsaSpendingApiError(f"count response missing transaction count: {payload!r}")

    def download_transactions(self, window: DateWindow, dest_csv: Path) -> DownloadResult:
        response = self._post_json(ENDPOINT_TRANSACTIONS, download_request_body(window))
        file_name = response.get("file_name")
        if not isinstance(file_name, str) or not file_name:
            raise UsaSpendingApiError(f"download response missing file_name: {response!r}")

        status_url = response.get("status_url")
        if not isinstance(status_url, str) or not status_url:
            status_url = f"{self._api_base}/download/status/?file_name={file_name}"

        file_url = self._wait_for_file(status_url, file_name)
        dest_csv.parent.mkdir(parents=True, exist_ok=True)
        zip_path = dest_csv.with_suffix(dest_csv.suffix + ".zip.tmp")
        try:
            self._download_file(file_url, zip_path)
            row_count = _extract_prime_csv(zip_path, dest_csv)
        finally:
            if zip_path.exists():
                zip_path.unlink()

        return DownloadResult(
            row_count=row_count,
            source_file_name=file_name,
            bytes_written=dest_csv.stat().st_size,
        )

    def _wait_for_file(self, status_url: str, file_name: str) -> str:
        for _ in range(_POLL_ATTEMPTS):
            status = self._get_json(status_url)
            state = str(status.get("status") or "").lower()
            file_url = status.get("file_url") or status.get("url")
            if isinstance(file_url, str) and file_url and state in {"finished", "ready", ""}:
                return file_url
            if state in {"failed", "error"}:
                raise UsaSpendingApiError(f"download failed for {file_name}: {status}")
            time.sleep(_POLL_SECONDS)
        raise UsaSpendingApiError(f"timed out waiting for download of {file_name}")

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._api_base}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": self._user_agent,
            },
            method="POST",
        )
        return self._read_json(req)

    def _get_json(self, url: str) -> dict[str, Any]:
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        return self._read_json(req)

    def _read_json(self, req: urllib.request.Request) -> dict[str, Any]:
        raw = self._open_bytes(req)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise UsaSpendingApiError(f"non-JSON response from {req.full_url}") from exc
        if not isinstance(parsed, dict):
            raise UsaSpendingApiError(f"expected JSON object from {req.full_url}")
        return parsed

    def _download_file(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp, tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(dest)
        except urllib.error.HTTPError as exc:
            if tmp.exists():
                tmp.unlink()
            detail = exc.read().decode("utf-8", errors="replace")
            raise UsaSpendingApiError(
                f"file download failed: {exc.code} {detail}"
            ) from exc
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise

    def _open_bytes(self, req: urllib.request.Request) -> bytes:
        last: BaseException | None = None
        for attempt in range(_HTTP_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise UsaSpendingApiError(
                    f"HTTP {exc.code} for {req.full_url}: {detail}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                if attempt + 1 >= _HTTP_RETRIES:
                    break
                time.sleep(1.0 * (attempt + 1))
        assert last is not None
        raise UsaSpendingApiError(f"request failed for {req.full_url}: {last}") from last


# === Zip Extract ===

def _extract_prime_csv(zip_path: Path, dest_csv: Path) -> int:
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
            raise UsaSpendingApiError(f"no PrimeTransactions CSV in {zip_path}")
        payload = zf.read(member)

    tmp = dest_csv.with_suffix(dest_csv.suffix + ".part")
    tmp.write_bytes(payload)
    tmp.replace(dest_csv)
    return _csv_data_rows(dest_csv)

def _csv_data_rows(path: Path) -> int:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return 0
    header = rows[0]
    missing = [c for c in TRANSACTION_DOWNLOAD_COLUMNS if c not in header]
    if missing:
        raise UsaSpendingApiError(
            f"downloaded CSV missing projected columns: {missing}"
        )
    return max(0, len(rows) - 1)
