# cy_th/materialize/transactions.py

"""Project `staging_valid` into canonical `transaction_fact` rows."""

# === Imports ===

from __future__ import annotations
from typing import Final
import duckdb

from cy_th.materialize.validate import TABLE_VALID
from cy_th.materialize.references import _require_table
from cy_th.schema.db_types import quote_ident


# === Constants ===

TABLE_TRANSACTIONS: Final[str] = "transaction_fact"
"""Canonical activity grain (`TransactionFact`)."""


# === Materialize ===

def materialize_transactions(conn: duckdb.DuckDBPyConnection) -> int:
    """Build `transaction_fact` from `staging_valid`.

    #### Returns:
        Row count written

    Raises `ValueError` if `staging_valid` is missing.
    """

    _require_table(conn, TABLE_VALID)

    conn.execute(f"DROP TABLE IF EXISTS {quote_ident(TABLE_TRANSACTIONS)}")
    conn.execute(
        f"""
        CREATE TABLE {quote_ident(TABLE_TRANSACTIONS)} AS
        SELECT
          {quote_ident('contract_transaction_unique_key')}
            AS {quote_ident('transaction_id')},
          {quote_ident('contract_award_unique_key')}
            AS {quote_ident('award_id')},
          {quote_ident('action_date')},
          {quote_ident('federal_action_obligation')},
          {quote_ident('modification_number')},
          {quote_ident('transaction_number')},
          {quote_ident('action_type_code')},
          {quote_ident('action_type')},
          {quote_ident('transaction_description')}
        FROM {quote_ident(TABLE_VALID)}
        """
    )

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(TABLE_TRANSACTIONS)}"
    ).fetchone()
    assert count_row is not None
    return int(count_row[0])
