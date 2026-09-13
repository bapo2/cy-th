# cy_th/schema/projection.py

"""USASpending transaction-download field projection for local materialization.

`TRANSACTION_DOWNLOAD_COLUMNS` is the exact `columns=` allowlist for `/download/transactions/`. It includes every source field required to build `TransactionFact`, `AwardRecord`, and reference rows. It excludes deferred enrichment dimensions (competition, pricing, set-aside, business flags, potential PoP end, congressional district, `date_signed`).
"""

# === Imports ===

from enum import StrEnum
from typing import Final, Mapping


# === Purpose Tags ===

class ColumnPurpose(StrEnum):
    """Why a download column is retained locally."""

    ACTIVITY = "activity"
    """Maps into `TransactionFact` (identity, dates, obligation, action text)"""

    AWARD_IDENTITY = "award_identity"
    """Award PIID / type on `AwardRecord`"""

    AWARD_TOPOLOGY = "award_topology"
    """Role FKs and relationship keys projected onto `AwardRecord` / refs"""

    AWARD_SEMANTICS = "award_semantics"
    """Descriptions, permalink, period of performance"""

    AWARD_SNAPSHOT = "award_snapshot"
    """Observed rolled-up money inputs (subject to snapshot quality rules)"""

    REF_DESCRIPTOR = "ref_descriptor"
    """Names / labels / descriptions for compact reference rows"""


# === Projection ===

TRANSACTION_DOWNLOAD_COLUMNS: Final[tuple[str, ...]] = (
    
    # TransactionFact / activity
    "contract_transaction_unique_key",
    "contract_award_unique_key",
    "action_date",
    "federal_action_obligation",
    "modification_number",
    "transaction_number",
    "action_type_code",
    "action_type",
    "transaction_description",
    
    # Award identity
    "award_id_piid",
    "award_type_code",
    
    # Recipient
    "recipient_uei",
    "recipient_name",
    "recipient_parent_uei",
    
    # Awarding org
    "awarding_agency_code",
    "awarding_agency_name",
    "awarding_sub_agency_code",
    "awarding_sub_agency_name",
    "awarding_office_code",
    "awarding_office_name",
    
    # Funding org
    "funding_agency_code",
    "funding_agency_name",
    "funding_sub_agency_code",
    "funding_sub_agency_name",
    "funding_office_code",
    "funding_office_name",
    
    # Parent IDV stub
    "parent_award_id_piid",
    "parent_award_agency_id",
    "parent_award_type_code",
    "parent_award_type",
    
    # Classifications
    "naics_code",
    "naics_description",
    "product_or_service_code",
    "product_or_service_code_description",
    
    # Award semantics
    "prime_award_base_transaction_description",
    "usaspending_permalink",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    
    # Observed money snapshot
    "total_dollars_obligated",
    "current_total_value_of_award",
    "potential_total_value_of_award",
    
    # Recipient location
    "recipient_country_code",
    "recipient_state_code",
    "prime_award_transaction_recipient_county_fips_code",
    "recipient_city_name",
    "recipient_zip_4_code",
    
    # PoP
    "primary_place_of_performance_country_code",
    "primary_place_of_performance_state_code",
    "prime_award_transaction_place_of_performance_county_fips_code",
    "primary_place_of_performance_city_name",
    "primary_place_of_performance_zip_4",
)
"""Ordered USASpending prime-transaction CSV columns requested at download-time."""


# === Column Purpose Mappings ===

COLUMN_PURPOSE: Final[Mapping[str, frozenset[ColumnPurpose]]] = {
    
    # TransactionFact / activity
    "contract_transaction_unique_key": frozenset({ColumnPurpose.ACTIVITY, ColumnPurpose.AWARD_TOPOLOGY, ColumnPurpose.AWARD_SNAPSHOT}),
    "contract_award_unique_key": frozenset({ColumnPurpose.ACTIVITY, ColumnPurpose.AWARD_IDENTITY, ColumnPurpose.AWARD_TOPOLOGY}),
    "action_date": frozenset({ColumnPurpose.ACTIVITY, ColumnPurpose.AWARD_TOPOLOGY, ColumnPurpose.AWARD_SNAPSHOT}),
    "federal_action_obligation": frozenset({ColumnPurpose.ACTIVITY}),
    "modification_number": frozenset({ColumnPurpose.ACTIVITY}),
    "transaction_number": frozenset({ColumnPurpose.ACTIVITY, ColumnPurpose.AWARD_SNAPSHOT}),
    "action_type_code": frozenset({ColumnPurpose.ACTIVITY}),
    "action_type": frozenset({ColumnPurpose.ACTIVITY}),
    "transaction_description": frozenset({ColumnPurpose.ACTIVITY}),
    
    # Award identity
    "award_id_piid": frozenset({ColumnPurpose.AWARD_IDENTITY}),
    "award_type_code": frozenset({ColumnPurpose.AWARD_IDENTITY}),
    
    # Recipient
    "recipient_uei": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "recipient_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "recipient_parent_uei": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    
    # Awarding org
    "awarding_agency_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "awarding_agency_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "awarding_sub_agency_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "awarding_sub_agency_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "awarding_office_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "awarding_office_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    
    # Funding org
    "funding_agency_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "funding_agency_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "funding_sub_agency_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "funding_sub_agency_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "funding_office_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "funding_office_name": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    
    # Parent IDV stub
    "parent_award_id_piid": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "parent_award_agency_id": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "parent_award_type_code": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "parent_award_type": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    
    # Classifications
    "naics_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "naics_description": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    "product_or_service_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "product_or_service_code_description": frozenset({ColumnPurpose.REF_DESCRIPTOR}),
    
    # Award semantics
    "prime_award_base_transaction_description": frozenset({ColumnPurpose.AWARD_SEMANTICS}),
    "usaspending_permalink": frozenset({ColumnPurpose.AWARD_SEMANTICS}),
    "period_of_performance_start_date": frozenset({ColumnPurpose.AWARD_SEMANTICS}),
    "period_of_performance_current_end_date": frozenset({ColumnPurpose.AWARD_SEMANTICS}),
    
    # Observed money snapshot
    "total_dollars_obligated": frozenset({ColumnPurpose.AWARD_SNAPSHOT}),
    "current_total_value_of_award": frozenset({ColumnPurpose.AWARD_SNAPSHOT}),
    "potential_total_value_of_award": frozenset({ColumnPurpose.AWARD_SNAPSHOT}),
    
    # Recipient location
    "recipient_country_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "recipient_state_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "prime_award_transaction_recipient_county_fips_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "recipient_city_name": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "recipient_zip_4_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    
    # PoP
    "primary_place_of_performance_country_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "primary_place_of_performance_state_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "prime_award_transaction_place_of_performance_county_fips_code": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "primary_place_of_performance_city_name": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
    "primary_place_of_performance_zip_4": frozenset({ColumnPurpose.AWARD_TOPOLOGY}),
}
"""Purpose annotations for each projected download column (covers the tuple)."""


# === Deferred Columns ===

DEFERRED_DOWNLOAD_COLUMNS: Final[tuple[str, ...]] = (
    "period_of_performance_potential_end_date",
    # NOTE: Competition / pricing / set-aside / business-type families are omitted wholesale
    # NOTE: Congressional districts are omitted from location identity
    # NOTE: `date_signed` / `award_base_action_date` are absent from the transaction export
)
"""Representative fields kept out of projection (lazy enrichment or out-of-scope for now)."""


# === Invariants Assertions ===

assert set(TRANSACTION_DOWNLOAD_COLUMNS) == set(COLUMN_PURPOSE), (
    "COLUMN_PURPOSE keys must exactly match TRANSACTION_DOWNLOAD_COLUMNS"
)
assert len(TRANSACTION_DOWNLOAD_COLUMNS) == len(set(TRANSACTION_DOWNLOAD_COLUMNS)), (
    "TRANSACTION_DOWNLOAD_COLUMNS must not have duplicates"
)
