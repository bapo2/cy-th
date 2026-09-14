# tests/cy_th/semantic/conftest.py

"""Shared fixtures for semantic index tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
from typing import Sequence
import pytest

from cy_th.materialize.pipeline import materialize
from cy_th.query.dataset import ProcurementDataset
from cy_th.semantic.build import build_semantic_index
from cy_th.semantic.embed import FakeEmbedder
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Dataset Fixture ===

@pytest.fixture
def semantic_data_root(tmp_path: Path) -> Path:
    """Materialize a small multi-theme set for semantic build / search tests.

    #### Awards:
        - `A_RADAR`: work-bearing radar / surveillance text
        - `A_FOOD`: catering / meals
        - `A_ENG`: engineering services (PSC + NAICS descriptions)
        - `A_EMPTY`: labels only (not indexable)
        - `A_TXN`: work only via transaction descriptions (newest-first / dedupe)
    """

    rows = [
        _award(
            "T_RADAR_1",
            "A_RADAR",
            "Radar detection and surveillance systems",
            "Install perimeter sensors",
            recipient_name="Radar Vendor",
        ),
        _award(
            "T_FOOD_1",
            "A_FOOD",
            "Catering and meal services for training",
            "Provide boxed lunches",
            recipient_name="Food Vendor",
        ),
        _award(
            "T_ENG_1",
            "A_ENG",
            "Engineering services for naval support",
            "Provide analysis",
            naics_code="541330",
            naics_description="Engineering Services",
            psc="R425",
            psc_description="Engineering and Technical Services",
            recipient_name="Eng Vendor",
        ),
        _award(
            "T_EMPTY_1",
            "A_EMPTY",
            "",
            "",
            naics_code="",
            naics_description="",
            psc="",
            psc_description="",
            recipient_name="Label Only LLC",
            awarding_agency_name="Department of Defense",
        ),
        _award(
            "T_TXN_OLD",
            "A_TXN",
            "",
            "Older duplicate work description",
            action_date="2025-01-01",
            naics_code="",
            naics_description="",
            psc="",
            psc_description="",
        ),
        _award(
            "T_TXN_NEW",
            "A_TXN",
            "",
            "Older DUPLICATE work description",  # Casefold-dedupe vs. older row
            action_date="2025-06-01",
            naics_code="",
            naics_description="",
            psc="",
            psc_description="",
        ),
        _award(
            "T_TXN_UNIQUE",
            "A_TXN",
            "",
            "Unique newer transaction work",
            action_date="2025-06-15",
            naics_code="",
            naics_description="",
            psc="",
            psc_description="",
        ),
    ]
    csv_path = write_projected_csv(tmp_path / "semantic_fixture.csv", rows)
    data_root = tmp_path / "data"
    materialize(
        [csv_path],
        out=data_root,
        run_id="20260914T190000Z_abcdef",
        allow_rejects=True,
    )
    return data_root

@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """Deterministic hash embedder (no Torch)."""

    return FakeEmbedder()

@pytest.fixture
def built_semantic_root(
    semantic_data_root: Path,
    fake_embedder: FakeEmbedder,
) -> Path:
    """Build and publish a FakeEmbedder index over `semantic_data_root`."""

    with ProcurementDataset.open(semantic_data_root) as ds:
        build_semantic_index(ds, fake_embedder, batch_size=8)
    return semantic_data_root


# === Helpers ===

def _award(
    txn_id: str,
    award_id: str,
    base_description: str,
    txn_description: str,
    *,
    action_date: str = "2025-06-15",
    naics_code: str = "541511",
    naics_description: str = "Custom Computer Programming Services",
    psc: str = "D302",
    psc_description: str = "IT and Telecom - Systems Development",
    recipient_name: str = "Vendor",
    awarding_agency_name: str = "Department of Defense",
) -> dict[str, str]:
    return blank_projected_row(
        contract_transaction_unique_key=txn_id,
        contract_award_unique_key=award_id,
        action_date=action_date,
        federal_action_obligation="1000.00",
        transaction_number="0",
        total_dollars_obligated="1000",
        current_total_value_of_award="1000",
        potential_total_value_of_award="1000",
        recipient_uei=f"UEI_{award_id}",
        recipient_name=recipient_name,
        awarding_agency_code="097",
        awarding_agency_name=awarding_agency_name,
        awarding_sub_agency_code="1700",
        awarding_sub_agency_name="DEPT OF THE NAVY",
        naics_code=naics_code,
        naics_description=naics_description,
        product_or_service_code=psc,
        product_or_service_code_description=psc_description,
        prime_award_base_transaction_description=base_description,
        transaction_description=txn_description,
    )

def materialize_rows(tmp_path: Path, rows: Sequence[dict[str, str]], *, run_id: str) -> Path:
    """Write `rows` and materialize under `tmp_path / data`."""

    csv_path = write_projected_csv(tmp_path / "in.csv", list(rows))
    data_root = tmp_path / "data"
    materialize([csv_path], out=data_root, run_id=run_id, allow_rejects=True)
    return data_root
