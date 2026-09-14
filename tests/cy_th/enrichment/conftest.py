# tests/cy_th/enrichment/conftest.py

"""Fixtures for enrichment overlay tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.materialize.pipeline import materialize
from cy_th.query.dataset import ProcurementDataset
from cy_th.schema.keys import idv_id
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Constants ===

DEF_AWARD = "CONT_AWD_DEF_9700_-NONE-_-NONE-"
REQ_AWARD = "CONT_AWD_REQ_9700_-NONE-_-NONE-"
PARENT_PIID = "SPE30023DS758"
PARENT_AGENCY = "9700"
IDV_ID = idv_id(piid=PARENT_PIID, award_key_agency_id=PARENT_AGENCY)


# === Dataset ===

@pytest.fixture
def enrich_data_root(tmp_path: Path) -> Path:
    """Published set with defensible + requires_enrichment Awards and one IDV stub."""

    rows = [
        blank_projected_row(
            contract_transaction_unique_key="T_DEF",
            contract_award_unique_key=DEF_AWARD,
            award_id_piid="PIID-DEF",
            action_date="2025-01-10",
            federal_action_obligation="100.00",
            total_dollars_obligated="100",
            current_total_value_of_award="100",
            potential_total_value_of_award="100",
            recipient_uei="UEI_ALPHA",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            funding_agency_code="097",
            funding_sub_agency_code="1700",
            funding_office_code="N00024",
            parent_award_id_piid=PARENT_PIID,
            parent_award_agency_id=PARENT_AGENCY,
            naics_code="541330",
            product_or_service_code="R425",
        ),
        # Same latest day, conflicting money → requires_enrichment
        blank_projected_row(
            contract_transaction_unique_key="T_REQ_A",
            contract_award_unique_key=REQ_AWARD,
            award_id_piid="PIID-REQ",
            action_date="2025-01-11",
            federal_action_obligation="10.00",
            total_dollars_obligated="100",
            current_total_value_of_award="100",
            potential_total_value_of_award="100",
            recipient_uei="UEI_ALPHA",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            funding_agency_code="097",
            funding_sub_agency_code="1700",
            funding_office_code="N00024",
            parent_award_id_piid=PARENT_PIID,
            parent_award_agency_id=PARENT_AGENCY,
            naics_code="541330",
            product_or_service_code="R425",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T_REQ_B",
            contract_award_unique_key=REQ_AWARD,
            award_id_piid="PIID-REQ",
            action_date="2025-01-11",
            federal_action_obligation="20.00",
            total_dollars_obligated="200",
            current_total_value_of_award="200",
            potential_total_value_of_award="200",
            recipient_uei="UEI_ALPHA",
            awarding_agency_code="097",
            awarding_sub_agency_code="1700",
            awarding_office_code="N00024",
            funding_agency_code="097",
            funding_sub_agency_code="1700",
            funding_office_code="N00024",
            parent_award_id_piid=PARENT_PIID,
            parent_award_agency_id=PARENT_AGENCY,
            naics_code="541330",
            product_or_service_code="R425",
        ),
    ]
    csv_path = write_projected_csv(tmp_path / "enrich_fixture.csv", rows)
    data_root = tmp_path / "data"
    materialize([csv_path], out=data_root, run_id="20260914T190000Z_e00101")
    return data_root

@pytest.fixture
def enrich_dataset(enrich_data_root: Path) -> ProcurementDataset:
    return ProcurementDataset.open(enrich_data_root)
