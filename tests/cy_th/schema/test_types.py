# tests/cy_th/schema/test_types.py

"""Tests for logical types and column specs."""

# === Imports ===

import pytest

from cy_th.schema.types import (
    BOOL,
    DATE,
    INT64,
    MONEY,
    STRING,
    LogicalType,
    TypeSpec,
    column,
    decimal,
    enum_type,
)


# === Vocabulary ===

def test_logical_type_vocabulary_is_closed() -> None:
    assert set(LogicalType) == {
        LogicalType.STRING,
        LogicalType.INT64,
        LogicalType.DECIMAL,
        LogicalType.DATE,
        LogicalType.BOOL,
        LogicalType.ENUM,
    }

def test_common_type_renders() -> None:
    assert STRING.render() == "string"
    assert INT64.render() == "int64"
    assert DATE.render() == "date"
    assert BOOL.render() == "bool"
    assert MONEY.render() == "decimal(20, 2)"
    assert enum_type("SnapshotStatus").render() == "enum:SnapshotStatus"


# === Validation ===

def test_decimal_requires_valid_precision_scale() -> None:
    with pytest.raises(ValueError, match="scale"):
        decimal(2, 3)
    with pytest.raises(ValueError, match="precision and scale"):
        TypeSpec(LogicalType.DECIMAL, precision=10)
    with pytest.raises(ValueError, match="precision must be"):
        decimal(0, 0)
    with pytest.raises(ValueError, match="enum_name"):
        TypeSpec(LogicalType.DECIMAL, precision=10, scale=2, enum_name="X")

def test_enum_rejects_precision() -> None:
    with pytest.raises(ValueError, match="precision/scale"):
        TypeSpec(LogicalType.ENUM, enum_name="SnapshotStatus", precision=1)

def test_enum_requires_name() -> None:
    with pytest.raises(ValueError, match="enum_name"):
        enum_type("")

def test_non_parameterized_types_reject_extra_fields() -> None:
    with pytest.raises(ValueError, match="must not set"):
        TypeSpec(LogicalType.STRING, precision=1)


# === ColumnSpec ===

def test_column_helper_sets_nullability() -> None:
    required = column("award_id", STRING, nullable=False, description="pk")
    optional = column("piid", STRING, nullable=True)
    assert required.name == "award_id"
    assert not required.nullable
    assert optional.nullable
    assert required.type is STRING
