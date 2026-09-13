# cy_th/schema/snapshot.py

"""Pure topology + money-snapshot derivation for one Award's local transactions.

Operates on in-memory row mappings (stdlib only). Topology/semantics selection and money-snapshot selection are intentionally separate rules.
"""

# === Imports ===

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Mapping, Sequence

from cy_th.schema.enums import SnapshotSource, SnapshotStatus


# === Constants ===

_TXN_ID: Final[str] = "transaction_id"
_ACTION_DATE: Final[str] = "action_date"
_TXN_NUMBER: Final[str] = "transaction_number"
_OBLIGATION: Final[str] = "total_dollars_obligated"
_CURRENT: Final[str] = "current_total_value_of_award"
_POTENTIAL: Final[str] = "potential_total_value_of_award"


# === Result ===

@dataclass(frozen=True, slots=True)
class AwardProjectionResult:
    """Topology provenance + money-snapshot fields for one `AwardRecord`."""

    projection_transaction_id: str
    """Txn chosen for topology/semantics (`MAX(action_date)`, then min txn id)."""

    snapshot_status: SnapshotStatus
    snapshot_source: SnapshotSource
    snapshot_transaction_id: str | None
    """Representative eligible txn when status is `defensible`, else `None`."""

    observed_total_obligation: Decimal | None
    observed_current_value: Decimal | None
    observed_potential_value: Decimal | None


# === Public API ===

def project_award_from_transactions(
    rows: Sequence[Mapping[str, Any]],
) -> AwardProjectionResult:
    """Derive Award topology id + money snapshot from one Award's local txns.

    #### Required Row Keys:
        - `transaction_id`
        - `action_date` (`date` or ISO `YYYY-MM-DD` string)
        - `transaction_number` (optional; eligibility uses `{0, "", null}`)
        - `total_dollars_obligated`
        - `current_total_value_of_award`
        - `potential_total_value_of_award`

    Money columns use USASpending download names because they're not stored on `TransactionFact`. Topology ignores `transaction_number` and avoids ordering by `modification_number`.
    """

    if not rows:
        raise ValueError("can't project Award from empty transaction group")

    projection_transaction_id = _select_topology_transaction_id(rows)
    return _project_money_snapshot(rows, projection_transaction_id=projection_transaction_id)


# === Topology ===

def _select_topology_transaction_id(rows: Sequence[Mapping[str, Any]]) -> str:
    """Pick the topology/semantics txn (latest `action_date`, then min txn ID)"""

    # Initialize best (latest) date and best transaction ID as None
    best_date: date | None = None
    best_id: str | None = None

    # Iterate over all rows to find the transaction with the latest action_date (or smallest txn_id if tied)
    for row in rows:
        txn_id = _require_txn_id(row)
        action_d = _parse_action_date(row.get(_ACTION_DATE))
        # Update if this row has a later date, or same date but smaller txn_id
        if best_date is None or action_d > best_date or (
            action_d == best_date and (best_id is None or txn_id < best_id)
        ):
            best_date = action_d
            best_id = txn_id
    
    # After loop, best_id must have been set
    assert best_id is not None
    return best_id


# === Money Snapshot ===

def _project_money_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    projection_transaction_id: str,
) -> AwardProjectionResult:
    """Apply the locked eligible-latest-day money snapshot rule."""

    # Filter rows to only include those where transaction_number is eligible (0, "", null)
    eligible = [row for row in rows if _is_snapshot_eligible(row.get(_TXN_NUMBER))]
    if not eligible:
        return _enrichment_result(projection_transaction_id)

    # Find the latest action_date among the eligible rows
    latest = max(_parse_action_date(row.get(_ACTION_DATE)) for row in eligible)
    candidates = [
        row for row in eligible if _parse_action_date(row.get(_ACTION_DATE)) == latest
    ]

    # Group eligible rows by action_date and find the money triples for each group
    money_rows = [_money_triple(row) for row in candidates]
    first = money_rows[0]
    if any(triple != first for triple in money_rows[1:]):
        return _enrichment_result(projection_transaction_id)

    # Check if all money triples are the same across all eligible rows
    obligation, current, potential = first
    null_count = sum(v is None for v in first)

    # If all money triples are null, return a NOT_OBSERVED result
    if null_count == 3:
        return AwardProjectionResult(
            projection_transaction_id=projection_transaction_id,
            snapshot_status=SnapshotStatus.NOT_OBSERVED,
            snapshot_source=SnapshotSource.TRANSACTION,
            snapshot_transaction_id=None,
            observed_total_obligation=None,
            observed_current_value=None,
            observed_potential_value=None,
        )

    # If there's partial nulls among the three fields, return an ENRICHMENT result (not defensible)
    if null_count != 0:
        return _enrichment_result(projection_transaction_id)

    # All three non-null and agreed across candidates, return a DEFENSIBLE result
    snapshot_txn_id = min(_require_txn_id(row) for row in candidates)
    return AwardProjectionResult(
        projection_transaction_id=projection_transaction_id,
        snapshot_status=SnapshotStatus.DEFENSIBLE,
        snapshot_source=SnapshotSource.TRANSACTION,
        snapshot_transaction_id=snapshot_txn_id,
        observed_total_obligation=obligation,
        observed_current_value=current,
        observed_potential_value=potential,
    )

def _enrichment_result(projection_transaction_id: str) -> AwardProjectionResult:
    """`requires_enrichment` with no observed money and `snapshot_source=none`."""

    return AwardProjectionResult(
        projection_transaction_id=projection_transaction_id,
        snapshot_status=SnapshotStatus.REQUIRES_ENRICHMENT,
        snapshot_source=SnapshotSource.NONE,
        snapshot_transaction_id=None,
        observed_total_obligation=None,
        observed_current_value=None,
        observed_potential_value=None,
    )


# === Parsing Helpers ===

def _require_txn_id(row: Mapping[str, Any]) -> str:
    """Require non-empty transaction ID"""
    raw = row.get(_TXN_ID)
    if raw is None:
        raise ValueError("transaction row missing transaction_id")
    txn_id = str(raw).strip()
    if not txn_id:
        raise ValueError("transaction_id must be non-empty")
    return txn_id

def _is_snapshot_eligible(transaction_number: Any) -> bool:
    """Eligible when `transaction_number ∈ {0, "", null}` (after strip)."""

    if transaction_number is None:
        return True
    if isinstance(transaction_number, int):
        return transaction_number == 0
    text = str(transaction_number).strip()
    return text == "" or text == "0"

def _parse_action_date(value: Any) -> date:
    """Parse action_date (datetime, date, or ISO string; raises on None)"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("action_date is required")
    
    # Attempt to parse as ISO string (YYYY-MM-DD) if not already a date / datetime
    text = str(value).strip()
    if not text:
        raise ValueError("action_date is required")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"invalid action_date: {value!r}") from exc

def _parse_money(value: Any) -> Decimal | None:
    """Parse money value (Decimal or None; raises on bool / invalid)"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("money field must not be bool")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):  # Avoid drift if caller accidentally passes float
        return Decimal(str(value))
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc

def _money_triple(row: Mapping[str, Any]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Extract money triples from a row"""
    return (
        _parse_money(row.get(_OBLIGATION)),
        _parse_money(row.get(_CURRENT)),
        _parse_money(row.get(_POTENTIAL)),
    )
