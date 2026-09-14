# cy_th/schema/types.py

"""Engine-neutral logical / storage types for canonical column contracts.

These types describe what we store (`string`, `date`, `decimal`, ...).

DuckDB physical binding lives in `db_types.py`.
"""

# === Imports ===

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


# === Type Kinds ===

class LogicalType(StrEnum):
    """Closed vocabulary of logical storage types."""

    STRING = "string"
    """UTF-8 text; we'll use for IDs, codes, names, and free text."""

    INT64 = "int64"
    """Signed 64-bit integer."""

    DECIMAL = "decimal"
    """Exact decimal; requires `precision` and `scale` on `TypeSpec`."""

    DATE = "date"
    """Calendar date (no tz)."""

    BOOL = "bool"
    """Boolean."""

    ENUM = "enum"
    """Constrained string; catalogued by `enum_name` (e.g. `SnapshotStatus`)."""


# === Type / Column Specs ===

@dataclass(frozen=True, slots=True)
class TypeSpec:
    """A concrete logical type, including parameters where required."""

    kind: LogicalType
    
    precision: int | None = None
    """Total significant digits for `decimal`; else `None`."""

    scale: int | None = None
    """Digits after the decimal point for `decimal`; else `None`."""

    enum_name: str | None = None
    """Catalog name for `enum` (matches a `StrEnum` type name); else `None`."""

    def __post_init__(self) -> None:
        if self.kind is LogicalType.DECIMAL:  # If the type is a decimal, check the precision and scale
            if self.precision is None or self.scale is None:
                raise ValueError("decimal requires precision and scale")
            if self.precision < 1:
                raise ValueError("decimal precision must be >= 1")
            if self.scale < 0 or self.scale > self.precision:
                raise ValueError("decimal scale must satisfy 0 <= scale <= precision")
            if self.enum_name is not None:
                raise ValueError("decimal must not set enum_name")
            return

        if self.kind is LogicalType.ENUM:  # If the type is an enum, check the enum_name
            if not self.enum_name or not self.enum_name.strip():
                raise ValueError("enum requires a non-empty enum_name")
            if self.precision is not None or self.scale is not None:  # We don't want these for enums
                raise ValueError("enum must not set precision/scale")
            return

        if self.precision is not None or self.scale is not None or self.enum_name is not None:  # We don't want these for other types either
            raise ValueError(f"{self.kind.value} must not set precision, scale, or enum_name")

    def render(self) -> str:
        """Render a stable type string (for debug/prints).

        #### Examples:
            - `string`
            - `decimal(20, 2)`
            - `enum:SnapshotStatus`
        """

        if self.kind is LogicalType.DECIMAL:
            return f"decimal({self.precision}, {self.scale})"
        if self.kind is LogicalType.ENUM:
            return f"enum:{self.enum_name}"
        return self.kind.value

@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column in a canonical record contract."""

    name: str
    type: TypeSpec
    nullable: bool
    description: str = ""
    """Short semantic note (optional).
    
    NOTE: Don't use as a substitute for `record-contracts.md`."""

Schema = tuple[ColumnSpec, ...]
"""Ordered column contract for a canonical record."""


# === Constructors ===

# Common TypeSpecs
STRING: Final[TypeSpec] = TypeSpec(LogicalType.STRING)
INT64: Final[TypeSpec] = TypeSpec(LogicalType.INT64)
DATE: Final[TypeSpec] = TypeSpec(LogicalType.DATE)
BOOL: Final[TypeSpec] = TypeSpec(LogicalType.BOOL)

def decimal(precision: int, scale: int) -> TypeSpec:
    """Build a `decimal(precision, scale)` type."""

    return TypeSpec(LogicalType.DECIMAL, precision=precision, scale=scale)

def enum_type(enum_name: str) -> TypeSpec:
    """Build an `enum` type keyed by catalog name (stored as string)."""

    return TypeSpec(LogicalType.ENUM, enum_name=enum_name.strip())

def column(
    name: str,
    type: TypeSpec,
    *,
    nullable: bool,
    description: str = "",
) -> ColumnSpec:
    """Build a `ColumnSpec` (we use keyword `nullable` for call-site clarity)."""

    return ColumnSpec(name=name, type=type, nullable=nullable, description=description)

MONEY: Final[TypeSpec] = decimal(20, 2)
"""Canonical money type for obligations and observed Award values."""