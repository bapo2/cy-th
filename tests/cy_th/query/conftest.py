# tests/cy_th/query/conftest.py

"""Shared fixtures for procurement query runtime tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.materialize.pipeline import materialize
from cy_th.query.dataset import ProcurementDataset
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Dataset Fixture ===

@pytest.fixture
def query_data_root(tmp_path: Path) -> Path:
    """Materialize a small multi-award set covering filter + aggregate cases.

    #### Awards:
        - `A1`: UEI_ALPHA; PoP VA / recipient VA; two dated txns (100 + 50)
        - `A2`: UEI_BETA; PoP MD / recipient VA; one txn (200)
        - `A3`: UEI_ALPHA; PoP CA; one txn (75) + one null-obligation txn
        - `A4`: UEI_GAMMA; Only null-obligation activity (excluded from ranked money)
    """

    rows = [
        blank_projected_row(
            contract_transaction_unique_key="T1A",
            contract_award_unique_key="A1",
            award_id_piid="PIID-A1",
            action_date="2025-01-10",
            federal_action_obligation="100.00",
            total_dollars_obligated="150",
            current_total_value_of_award="150",
            potential_total_value_of_award="150",
            recipient_uei="UEI_ALPHA",
            recipient_name="Alpha Corp",
            awarding_agency_code="097",
            awarding_agency_name="Department of Defense",
            awarding_sub_agency_code="1700",
            awarding_sub_agency_name="DEPT OF THE NAVY",
            awarding_office_code="N00024",
            awarding_office_name="NAVSEA",
            funding_agency_code="097",
            funding_sub_agency_code="1700",
            funding_office_code="N00024",
            naics_code="541330",
            naics_description="Engineering Services",
            product_or_service_code="R425",
            product_or_service_code_description="Support",
            usaspending_permalink="https://example.test/award/A1",
            recipient_country_code="USA",
            recipient_state_code="VA",
            recipient_city_name="Arlington",
            recipient_zip_4_code="22202",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="VA",
            primary_place_of_performance_city_name="Arlington",
            primary_place_of_performance_zip_4="22202",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T1B",
            contract_award_unique_key="A1",
            award_id_piid="PIID-A1",
            action_date="2025-02-10",
            federal_action_obligation="50.00",
            total_dollars_obligated="150",
            current_total_value_of_award="150",
            potential_total_value_of_award="150",
            recipient_uei="UEI_ALPHA",
            recipient_name="Alpha Corp",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            funding_agency_code="097",
            funding_sub_agency_code="1700",
            funding_office_code="N00024",
            naics_code="541330",
            product_or_service_code="R425",
            usaspending_permalink="https://example.test/award/A1",
            recipient_country_code="USA",
            recipient_state_code="VA",
            recipient_city_name="Arlington",
            recipient_zip_4_code="22202",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="VA",
            primary_place_of_performance_city_name="Arlington",
            primary_place_of_performance_zip_4="22202",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T2",
            contract_award_unique_key="A2",
            award_id_piid="PIID-A2",
            action_date="2025-01-15",
            federal_action_obligation="200.00",
            total_dollars_obligated="200",
            current_total_value_of_award="200",
            potential_total_value_of_award="200",
            recipient_uei="UEI_BETA",
            recipient_name="Beta LLC",
            awarding_agency_code="097",
            awarding_sub_agency_code="5700",
            awarding_office_code="W15P7T",
            funding_agency_code="097",
            funding_sub_agency_code="5700",
            funding_office_code="W15P7T",
            naics_code="336411",
            product_or_service_code="1510",
            usaspending_permalink="https://example.test/award/A2",
            recipient_country_code="USA",
            recipient_state_code="VA",
            recipient_city_name="Reston",
            recipient_zip_4_code="20190",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="MD",
            primary_place_of_performance_city_name="Bethesda",
            primary_place_of_performance_zip_4="20814",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T3A",
            contract_award_unique_key="A3",
            award_id_piid="PIID-A3",
            action_date="2025-01-20",
            federal_action_obligation="75.00",
            total_dollars_obligated="75",
            current_total_value_of_award="75",
            potential_total_value_of_award="75",
            recipient_uei="UEI_ALPHA",
            recipient_name="Alpha Corp",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            naics_code="541330",
            product_or_service_code="R425",
            usaspending_permalink="https://example.test/award/A3",
            recipient_country_code="USA",
            recipient_state_code="VA",
            recipient_city_name="Arlington",
            recipient_zip_4_code="22202",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="CA",
            primary_place_of_performance_city_name="San Diego",
            primary_place_of_performance_zip_4="92101",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T3B",
            contract_award_unique_key="A3",
            award_id_piid="PIID-A3",
            action_date="2025-01-21",
            federal_action_obligation="",  # Null obligation
            total_dollars_obligated="75",
            current_total_value_of_award="75",
            potential_total_value_of_award="75",
            recipient_uei="UEI_ALPHA",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            naics_code="541330",
            product_or_service_code="R425",
            usaspending_permalink="https://example.test/award/A3",
            recipient_country_code="USA",
            recipient_state_code="VA",
            recipient_city_name="Arlington",
            recipient_zip_4_code="22202",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="CA",
            primary_place_of_performance_city_name="San Diego",
            primary_place_of_performance_zip_4="92101",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T4",
            contract_award_unique_key="A4",
            award_id_piid="PIID-A4",
            action_date="2025-01-12",
            federal_action_obligation="",  # Only null money → excluded from ranked results
            total_dollars_obligated="",
            current_total_value_of_award="",
            potential_total_value_of_award="",
            recipient_uei="UEI_GAMMA",
            recipient_name="Gamma Inc",
            awarding_agency_code="097",
            usaspending_permalink="https://example.test/award/A4",
            primary_place_of_performance_country_code="USA",
            primary_place_of_performance_state_code="TX",
            primary_place_of_performance_city_name="Austin",
        ),
    ]
    csv_path = write_projected_csv(tmp_path / "query_fixture.csv", rows)
    data_root = tmp_path / "data"
    materialize(
        [csv_path],
        out=data_root,
        run_id="20260914T180000Z_abcdef",
    )
    return data_root

@pytest.fixture
def dataset(query_data_root: Path) -> ProcurementDataset:
    """Open the synthetic query fixture (close via context or explicit `close`)."""

    return ProcurementDataset.open(query_data_root)
