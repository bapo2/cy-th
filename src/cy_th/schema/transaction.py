# cy_th/schema/transaction.py

"""Logical column contract for canonical transaction activity facts."""

# === Imports ===

from cy_th.schema.types import (
    DATE,
    MONEY,
    STRING,
    Schema,
    column,
)


# === TransactionFact ===

TRANSACTION_FACT_SCHEMA: Schema = (
    column(
        "transaction_id",
        STRING,
        nullable=False,
        description="Primary key USASpending `contract_transaction_unique_key`",
    ),
    column(
        "award_id",
        STRING,
        nullable=False,
        description="Parent Award key `contract_award_unique_key`",
    ),
    column(
        "action_date",
        DATE,
        nullable=False,
        description="Procurement action date (`action_date`, window filter grain)",
    ),
    column(
        "federal_action_obligation",
        MONEY,
        nullable=True,
        description="Obligation delta for this action (can be negative)",
    ),
    column(  # Not to be used as a temporal sort key
        "modification_number",
        STRING,
        nullable=True,
        description="Modification identity",
    ),
    column(
        "transaction_number",
        STRING,
        nullable=True,
        description="Within-mod sequence (money snapshot eligibility uses {0,\"\",null})",
    ),
    column(
        "action_type_code",
        STRING,
        nullable=True,
        description="Action type code when present on the txn export",
    ),
    column(
        "action_type",
        STRING,
        nullable=True,
        description="Action type label when present on the txn export",
    ),
    column(
        "transaction_description",
        STRING,
        nullable=True,
        description="Action-specific description text for semantic / citation use",
    ),
)
"""Authoritative local grain for time-bounded activity (`SUM` of obligations).

We project Award topology and observed money state separately onto `AwardRecord`.
"""
