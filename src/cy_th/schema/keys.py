# cy_th/schema/keys.py

"""Deterministic identity helpers for canonical reference records."""

# === Imports ===

from hashlib import sha256
from typing import Final

from cy_th.schema.enums import AgencyTier, ClassificationKind


# === Constants ===

_LOC_SEP: Final[str] = "\x1f"
"""Field separator for location canonicalization (unlikely in geo codes/names)."""


# === Agency ===

def agency_id(*, tier: AgencyTier, code: str) -> str:
    """Build an `AgencyRef` ID from `(tier, code)`.

    Uses the `*_agency_code` namespace (e.g. `097`), not award-key agency IDs (e.g. `9700`).

    #### Form:
        `{tier}:{code}` (e.g. `toptier:097`, `subtier:97AS`)
    """

    code_n = code.strip()
    if not code_n:
        raise ValueError("agency code must be non-empty")
    return f"{tier.value}:{code_n}"


# === Classification ===

def classification_id(kind: ClassificationKind, code: str) -> str:
    """Build a namespaced classification ID.

    #### Examples:
        - `NAICS:541330`
        - `PSC:R425`
    """

    normalized = code.strip()
    if not normalized:
        raise ValueError("classification code must be non-empty")
    return f"{kind.value}:{normalized}"


# === IDV ===

def idv_id(*, piid: str, award_key_agency_id: str) -> str:
    """Build a generated IDV key from child parent fields.

    Uses the award-key agency namespace (e.g. `9700`), **not** `AgencyRef` codes (e.g. `097`).

    #### Form:
        `CONT_IDV_{piid}_{award_key_agency_id}`
    """

    piid_n = piid.strip()
    agency_n = award_key_agency_id.strip()
    if not piid_n or not agency_n:
        raise ValueError("piid and award_key_agency_id must be non-empty")
    return f"CONT_IDV_{piid_n}_{agency_n}"


# === Office ===

def office_id(*, sub_agency_code: str, office_code: str) -> str | None:
    """Build an office ID namespaced under subtier, or `None` if incomplete.

    #### Form:
        `{sub_agency_code}:{office_code}`

    #### Returns:
        `None` when `office_code` is missing/blank so callers do not manufacture an `OfficeRef`
    """

    office_n = office_code.strip()
    if not office_n:
        return None
    sub_n = sub_agency_code.strip()
    if not sub_n:
        raise ValueError("sub_agency_code must be non-empty when office_code is present")
    return f"{sub_n}:{office_n}"


# === Location ===

def normalize_city_name(city: str | None) -> str:
    """Normalize a city label for location identity (strip + `lower()`)."""

    if city is None:
        return ""
    return city.strip().lower()

def location_id(
    *,
    country_code: str | None = None,
    state_code: str | None = None,
    county_fips: str | None = None,
    city_name: str | None = None,
    zip_code: str | None = None,
) -> str | None:
    """Build a local location ID from the strongest available geo-components.

    #### Identity Tuple:
    (codes preferred; city is a normalized label fallback)
    
        - `country_code`
        - `state_code`
        - `county_fips`
        - normalized `city_name`
        - `zip`

    Congressional district is intentionally excluded. The returned value is a hex SHA-256 digest of the canonical tuple (not a UEI-grade geo-ID).

    #### Returns:
        - Hex SHA-256 digest of the canonical tuple when any geo component is present
        - `None` when every geo component is blank
    """

    parts = (
        _norm_code(country_code),
        _norm_code(state_code),
        _norm_code(county_fips),
        normalize_city_name(city_name),
        _norm_code(zip_code),
    )
    if not any(parts):
        return None
    payload = _LOC_SEP.join(parts).encode("utf-8")
    return sha256(payload).hexdigest()

def location_granularity(
    *,
    country_code: str | None = None,
    state_code: str | None = None,
    county_fips: str | None = None,
    city_name: str | None = None,
    zip_code: str | None = None,
) -> str:
    """Return a slash-path describing which identity components are present.

    #### Example:
        `country/state/county/city/zip` or `country/state`
    """

    labels: list[str] = []
    if _norm_code(country_code):
        labels.append("country")
    if _norm_code(state_code):
        labels.append("state")
    if _norm_code(county_fips):
        labels.append("county")
    if normalize_city_name(city_name):
        labels.append("city")
    if _norm_code(zip_code):
        labels.append("zip")
    return "/".join(labels) if labels else "empty"


# === Private Helpers ===

def _norm_code(value: str | None) -> str:
    """Strip whitespace only; preserve case for official geo-codes."""

    if value is None:
        return ""
    return value.strip()
