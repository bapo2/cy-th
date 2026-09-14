# tests/cy_th/schema/test_db_types.py

"""Tests for DuckDB physical bindings of logical column contracts."""

# === Imports ===

import pytest

from cy_th.schema.db_types import (
    blank_as_null_expr,
    cast_expr,
    create_table_sql,
    duckdb_type,
    quote_ident,
    typed_select_list,
)
from cy_th.schema.transaction import TRANSACTION_FACT_SCHEMA
from cy_th.schema.types import BOOL, DATE, INT64, MONEY, STRING, column, enum_type


# === Type Mapping ===

def test_duckdb_type_mapping() -> None:
    assert duckdb_type(STRING) == "VARCHAR"
    assert duckdb_type(INT64) == "BIGINT"
    assert duckdb_type(DATE) == "DATE"
    assert duckdb_type(BOOL) == "BOOLEAN"
    assert duckdb_type(MONEY) == "DECIMAL(20, 2)"
    assert duckdb_type(enum_type("SnapshotStatus")) == "VARCHAR"

def test_quote_ident_escapes_embedded_quotes() -> None:
    assert quote_ident('a"b') == '"a""b"'


# === DDL / Casts ===

def test_create_table_sql_includes_not_null() -> None:
    ddl = create_table_sql("transaction_fact", TRANSACTION_FACT_SCHEMA)
    assert 'CREATE TABLE "transaction_fact"' in ddl
    assert '"transaction_id" VARCHAR NOT NULL' in ddl
    assert '"federal_action_obligation" DECIMAL(20, 2)' in ddl
    assert "NOT NULL" in ddl

def test_create_table_sql_rejects_empty_schema() -> None:
    with pytest.raises(ValueError, match="at least one"):
        create_table_sql("empty", ())

def test_cast_expr_blank_to_null_for_strings() -> None:
    expr = blank_as_null_expr(quote_ident("piid"))
    assert "THEN NULL" in expr
    assert "TRIM" in expr

def test_cast_expr_try_cast_for_money() -> None:
    expr = cast_expr(quote_ident("federal_action_obligation"), MONEY)
    assert "TRY_CAST" in expr
    assert "DECIMAL(20, 2)" in expr

def test_typed_select_list_with_source_alias() -> None:
    schema = (column("action_date", DATE, nullable=False),)
    sql = typed_select_list(schema, source="raw")
    assert '"raw"."action_date"' in sql
    assert 'AS "action_date"' in sql
