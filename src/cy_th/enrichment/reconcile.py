# cy_th/enrichment/reconcile.py

"""Map USASpending award-detail payloads into selected overlay fields."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from cy_th.enrichment.types import AwardSelected, IdvSelected, LocalAwardRow
from cy_th.schema.enums import SnapshotSource, SnapshotStatus


# === Parse Payload ===

def select_award_fields(payload: Mapping[str, Any]) -> AwardSelected:
    """Extract enrichment fields from an award-detail JSON body."""

    return AwardSelected(
        date_signed=_iso_date_str(payload.get("date_signed")),
        total_obligation=_money_str(payload.get("total_obligation")),
        current_value=_money_str(payload.get("base_exercised_options")),
        potential_value=_money_str(payload.get("base_and_all_options")),
        type_code=_optional_str(payload.get("type")),
        type_label=_optional_str(payload.get("type_description")),
    )

def select_idv_fields(payload: Mapping[str, Any]) -> IdvSelected:
    """Extract IDV hydration fields from an award-detail JSON body."""

    return IdvSelected(
        type_code=_optional_str(payload.get("type")),
        type_label=_optional_str(payload.get("type_description")),
        date_signed=_iso_date_str(payload.get("date_signed")),
    )


# === Overlay Money ===

def overlay_award_money(
    local: LocalAwardRow,
    selected: AwardSelected,
) -> tuple[bool, Decimal | None, Decimal | None, Decimal | None, SnapshotStatus, SnapshotSource]:
    """Decide overlay money from local status + selected detail fields.

    Money from award detail is applied **only** when local `snapshot_status` is `requires_enrichment`. Defensible / `not_observed` local money is preserved.
    """

    if local.snapshot_status is not SnapshotStatus.REQUIRES_ENRICHMENT:
        return (
            False,
            local.observed_total_obligation,
            local.observed_current_value,
            local.observed_potential_value,
            local.snapshot_status,
            local.snapshot_source,
        )

    total = _parse_money(selected.total_obligation)
    current = _parse_money(selected.current_value)
    potential = _parse_money(selected.potential_value)
    if total is not None and current is not None and potential is not None:
        return (
            True,
            total,
            current,
            potential,
            SnapshotStatus.DEFENSIBLE,
            SnapshotSource.AWARD_DETAIL,
        )
    return (
        True,
        total,
        current,
        potential,
        SnapshotStatus.REQUIRES_ENRICHMENT,
        SnapshotSource.AWARD_DETAIL,
    )

def parse_date_signed(selected: AwardSelected) -> date | None:
    if selected.date_signed is None:
        return None
    try:
        return date.fromisoformat(selected.date_signed[:10])
    except ValueError:
        return None


# === Helpers ===

def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None

def _iso_date_str(value: object) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    return text[:10]

def _money_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return format(Decimal(str(value)), "f")
    text = str(value).strip()
    return text if text else None

def _parse_money(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None
