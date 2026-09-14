# cy_th/schema/references.py

"""Logical column contracts for compact reference records.

Reference rows are relationship targets for `AwardRecord` FKs. They carry stable identity plus enough descriptive fields for local querying.
"""

# === Imports ===

from cy_th.schema.types import (
    STRING,
    Schema,
    column,
    enum_type,
)


# === Shared Enum Types ===

_AGENCY_TIER = enum_type("AgencyTier")
_CLASSIFICATION_KIND = enum_type("ClassificationKind")
_HYDRATION_STATUS = enum_type("HydrationStatus")


# === AgencyRef ===

AGENCY_REF_SCHEMA: Schema = (
    column(
        "agency_id",
        STRING,
        nullable=False,
        description="Primary key `{tier}:{code}` from `agency_id()` / `*_agency_code`",
    ),
    column(
        "tier",
        _AGENCY_TIER,
        nullable=False,
        description="`toptier` or `subtier` (logical identity with `code`)",
    ),
    column(
        "code",
        STRING,
        nullable=False,
        description="USASpending `*_agency_code` / `*_sub_agency_code`",
    ),
    column(
        "name",
        STRING,
        nullable=True,
        description="Best-known agency display name from the local txn population",
    ),
)
"""Government organization in the `*_agency_code` namespace.

Identity is `(tier, code)`, encoded as `agency_id`.
"""


# === OfficeRef ===

OFFICE_REF_SCHEMA: Schema = (
    column(
        "office_id",
        STRING,
        nullable=False,
        description="Primary key `{sub_agency_code}:{office_code}` from `office_id()`",
    ),
    column(
        "sub_agency_code",
        STRING,
        nullable=False,
        description="Parent subtier `*_sub_agency_code` namespace for the office",
    ),
    column(  # Absent codes shouldn't create a row!
        "office_code",
        STRING,
        nullable=False,
        description="USASpending `*_office_code`",
    ),
    column(
        "name",
        STRING,
        nullable=True,
        description="Best-known office display name from the local txn population",
    ),
)
"""Office namespaced under subtier.

Same row might appear in awarding or funding roles.
"""


# === RecipientRef ===

RECIPIENT_REF_SCHEMA: Schema = (
    column(
        "uei",
        STRING,
        nullable=False,
        description="Primary key USASpending `recipient_uei` (Award `recipient_id` FK)",
    ),
    column(  # Not an identity component!
        "name",
        STRING,
        nullable=True,
        description="Best-known recipient display name",
    ),
    column(
        "parent_uei",
        STRING,
        nullable=True,
        description="Parent organization UEI when present (`recipient_parent_uei`)",
    ),
)
"""Award recipient.

Parentage lives here (shouldn't be duplicated onto every `AwardRecord`).
"""


# === ClassificationRef ===

CLASSIFICATION_REF_SCHEMA: Schema = (
    column(
        "classification_id",
        STRING,
        nullable=False,
        description="Primary key `NAICS:{code}` or `PSC:{code}` from `classification_id()`",
    ),
    column(
        "kind",
        _CLASSIFICATION_KIND,
        nullable=False,
        description="Discriminator for kind (`NAICS` or `PSC`)",
    ),
    column(
        "code",
        STRING,
        nullable=False,
        description="Classification code (`naics_code` or `product_or_service_code`)",
    ),
    column(
        "description",
        STRING,
        nullable=True,
        description="Source classification description (when available)",
    ),
)
"""One table for NAICS and PSC.

`AwardRecord` keeps separate `naics_id` / `psc_id` FKs.
"""


# === IDVRef ===

IDV_REF_SCHEMA: Schema = (
    column(
        "idv_id",
        STRING,
        nullable=False,
        description="Primary key `CONT_IDV_{piid}_{award_key_agency_id}` from `idv_id()`",
    ),
    column(
        "piid",
        STRING,
        nullable=False,
        description="Parent vehicle PIID from `parent_award_id_piid`",
    ),
    column(
        "award_key_agency_id",
        STRING,
        nullable=False,
        description="Award-key agency component from `parent_award_agency_id`",
    ),
    column(
        "type_code",
        STRING,
        nullable=True,
        description="Parent award type code when present on the child txn row",
    ),
    column(
        "type_label",
        STRING,
        nullable=True,
        description="Parent award type label when present on the child txn row",
    ),
    column(
        "hydration_status",
        _HYDRATION_STATUS,
        nullable=False,
        description="`stub` from child fields (`hydrated` after enrichment)",
    ),
)
"""Referenced IDV stub.

Not part of the primary activity population (we'll hydrate lazily).
"""


# === LocationRef ===

LOCATION_REF_SCHEMA: Schema = (  # NOTE: Congressional district intentionally excluded from identity
    column(
        "location_id",
        STRING,
        nullable=False,
        description="Primary key SHA-256 hex digest from `location_id()` over the geo-tuple",
    ),
    column(
        "country_code",
        STRING,
        nullable=True,
        description="Country code component of location identity",
    ),
    column(
        "state_code",
        STRING,
        nullable=True,
        description="State / province code component of location identity",
    ),
    column(
        "county_fips",
        STRING,
        nullable=True,
        description="County FIPS component of location identity",
    ),
    column(  # Strip + lower() this
        "city_name",
        STRING,
        nullable=True,
        description="Normalized city label used in identity",
    ),
    column(
        "zip_code",
        STRING,
        nullable=True,
        description="Postal / ZIP component of location identity",
    ),
    column(
        "granularity",
        STRING,
        nullable=False,
        description="Slash-path of present components from `location_granularity()`",
    ),
)
"""Weak deterministic geo value-object."""
