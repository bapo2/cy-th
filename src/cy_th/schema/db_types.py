# cy_th/schema/db_types.py

"""DuckDB physical bindings for logical column contracts.

Maps `TypeSpec` / `ColumnSpec` / `Schema` to DuckDB DDL and cast expressions. Enums stay `VARCHAR` (catalog enforcement is application-side).
"""

# === Imports ===

from typing import Final

from cy_th.schema.types import ColumnSpec, LogicalType, Schema, TypeSpec


# === Identifiers ===

def quote_ident(name: str) -> str:
    """Quote a DuckDB identifier (double quotes; escape embedded quotes)."""

    return '"' + name.replace('"', '""') + '"'


# === Type Mapping ===

def duckdb_type(spec: TypeSpec) -> str:
    """Render a DuckDB type for a logical `TypeSpec`.

    #### Mapping:
        - `string` / `enum` → `VARCHAR`
        - `int64` → `BIGINT`
        - `decimal(p, s)` → `DECIMAL(p, s)`
        - `date` → `DATE`
        - `bool` → `BOOLEAN`
    """

    kind = spec.kind
    if kind is LogicalType.STRING or kind is LogicalType.ENUM:
        return "VARCHAR"
    if kind is LogicalType.INT64:
        return "BIGINT"
    if kind is LogicalType.DECIMAL:
        return f"DECIMAL({spec.precision}, {spec.scale})"
    if kind is LogicalType.DATE:
        return "DATE"
    if kind is LogicalType.BOOL:
        return "BOOLEAN"
    raise ValueError(f"unsupported logical type: {kind!r}")

def column_ddl(col: ColumnSpec) -> str:
    """Render one column clause (`"name" TYPE [NOT NULL]`)."""

    nullability = "" if col.nullable else " NOT NULL"
    return f"{quote_ident(col.name)} {duckdb_type(col.type)}{nullability}"

def create_table_sql(
    table: str,
    schema: Schema,
    *,
    if_not_exists: bool = False,
) -> str:
    """Build `CREATE TABLE` DDL from a logical `Schema`."""

    if not schema:
        raise ValueError("schema must have at least one column")

    exists = " IF NOT EXISTS" if if_not_exists else ""
    body = ",\n  ".join(column_ddl(col) for col in schema)
    return f"CREATE TABLE{exists} {quote_ident(table)} (\n  {body}\n)"


# === Cast Expressions ===

_BLANK_SQL: Final[str] = "TRIM(CAST({col} AS VARCHAR)) = ''"  # Used to detect blank values

def blank_as_null_expr(column_ref: str) -> str:
    """Blank / whitespace-only text → NULL, else trimmed text.

    `column_ref` is an already-valid SQL column ref.
    """

    trimmed = f"TRIM(CAST({column_ref} AS VARCHAR))"
    return f"CASE WHEN {column_ref} IS NULL OR {_BLANK_SQL.format(col=column_ref)} THEN NULL ELSE {trimmed} END"

def cast_expr(column_ref: str, spec: TypeSpec) -> str:
    """Cast a CSV/text column ref to the DuckDB type for `spec`.

    Blank / whitespace-only values become NULL. Non-blank values use `TRY_CAST` for non-text kinds so malformed input yields NULL (callers detect rejects by comparing blank vs. failed cast).
    """

    if spec.kind is LogicalType.STRING or spec.kind is LogicalType.ENUM:
        return blank_as_null_expr(column_ref)

    target = duckdb_type(spec)
    trimmed = f"TRIM(CAST({column_ref} AS VARCHAR))"
    return (
        f"CASE WHEN {column_ref} IS NULL OR {_BLANK_SQL.format(col=column_ref)} "
        f"THEN NULL ELSE TRY_CAST({trimmed} AS {target}) END"
    )

def typed_select_list(schema: Schema, *, source: str | None = None) -> str:
    """Build a `SELECT` list casting each schema column from a source relation.

    When `source` is set, columns are read as `{source}."col"`, else bare `"col"`.
    """

    parts: list[str] = []
    for col in schema:
        ref = (
            f"{quote_ident(source)}.{quote_ident(col.name)}"
            if source is not None
            else quote_ident(col.name)
        )
        parts.append(f"{cast_expr(ref, col.type)} AS {quote_ident(col.name)}")
    return ",\n  ".join(parts)
