# cy_th/enrichment/client.py

"""Live USASpending award-detail HTTP client."""

# === Imports ===

from __future__ import annotations
from typing import Any
import json
import time
import urllib.error
import urllib.request

from cy_th.enrichment.cache import award_detail_endpoint
from cy_th.enrichment.errors import UsaSpendingDetailError
from cy_th.ingest.filters import API_BASE


# === Constants ===

USER_AGENT: str = "Mozilla/5.0 (compatible; cy-th-enrichment/0.1)"
_HTTP_RETRIES: int = 4


# === Client ===

class UsaSpendingDetailClient:
    """Live `GET /awards/{id}/` client."""

    def __init__(
        self,
        *,
        api_base: str = API_BASE,
        user_agent: str = USER_AGENT,
        timeout: float = 60.0,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout

    def fetch_award_detail(self, source_id: str) -> dict[str, Any]:
        url = award_detail_endpoint(source_id)
        if self._api_base != API_BASE:
            url = f"{self._api_base}/awards/{source_id}/"
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        raw = self._open_bytes(req)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise UsaSpendingDetailError(f"non-JSON response from {url}") from exc
        if not isinstance(parsed, dict):
            raise UsaSpendingDetailError(f"expected JSON object from {url}")
        return parsed

    def _open_bytes(self, req: urllib.request.Request) -> bytes:
        last: BaseException | None = None
        for attempt in range(_HTTP_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise UsaSpendingDetailError(
                    f"HTTP {exc.code} for {req.full_url}: {detail}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                if attempt + 1 >= _HTTP_RETRIES:
                    break
                time.sleep(1.0 * (attempt + 1))
        assert last is not None
        raise UsaSpendingDetailError(f"request failed for {req.full_url}: {last}") from last
