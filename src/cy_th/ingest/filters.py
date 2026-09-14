# cy_th/ingest/filters.py

"""Locked primary-population filters for USASpending transaction download."""

# === Imports ===

from __future__ import annotations
from typing import Any

from cy_th.ingest.types import DateWindow
from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS


# === Constants ===

AWARDING_AGENCY_NAME: str = "Department of Defense"
AWARD_TYPE_CODES: tuple[str, ...] = ("A", "B", "C", "D")
ENDPOINT_COUNT: str = "/download/count/"
ENDPOINT_TRANSACTIONS: str = "/download/transactions/"
API_BASE: str = "https://api.usaspending.gov/api/v2"
DOWNLOAD_ROW_CAP: int = 500_000
"""USASpending `/download/transactions/` row limit (subdivide when count exceeds this)."""


# === Request Bodies ===

def population_filters(window: DateWindow) -> dict[str, Any]:
    """USASpending `filters` object for the locked prime DoD population."""

    return {
        "agencies": [
            {
                "type": "awarding",
                "tier": "toptier",
                "name": AWARDING_AGENCY_NAME,
            }
        ],
        "time_period": [
            {
                "start_date": window.start.isoformat(),
                "end_date": window.end.isoformat(),
                "date_type": "action_date",
            }
        ],
        "award_type_codes": list(AWARD_TYPE_CODES),
    }

def download_request_body(window: DateWindow) -> dict[str, Any]:
    """POST body for `/download/transactions/` (projected columns)."""

    return {
        "filters": population_filters(window),
        "columns": list(TRANSACTION_DOWNLOAD_COLUMNS),
        "file_format": "csv",
    }

def count_request_body(window: DateWindow) -> dict[str, Any]:
    """POST body for `/download/count/`."""

    return {"filters": population_filters(window)}
