# tests/cy_th/query/test_traverse.py

"""Tests for one-hop `traverse_relationships`."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.materialize.pipeline import materialize
from cy_th.query.dataset import ProcurementDataset
from cy_th.query.errors import StaleSelectionError
from cy_th.query.types import (
    AwardFilters,
    EntityKind,
    LocationFilter,
    LocationRole,
    RelationRole,
)
from cy_th.schema.enums import AgencyTier, ClassificationKind
from cy_th.schema.keys import agency_id, classification_id, idv_id, office_id
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Fixtures ===

@pytest.fixture
def traverse_data_root(tmp_path: Path) -> Path:
    """Small set covering roles, dedupe, nulls, IDV, and location roles.

    #### Awards:
        - `A_SHARED`: awarding + funding same DoD/Navy/NAVSEA; shared recipient; parent IDV
        - `A_OTHER`: same recipient (dedupe); different funding office (Army)
        - `A_SPARSE`: recipient only (no agency subtier/office/classifications/IDV)
    """

    shared = dict(
        recipient_uei="UEI_ALPHA",
        recipient_name="Alpha Corp",
        awarding_agency_code="097",
        awarding_agency_name="Department of Defense",
        awarding_sub_agency_code="1700",
        awarding_sub_agency_name="DEPT OF THE NAVY",
        awarding_office_code="N00024",
        awarding_office_name="NAVSEA",
        funding_agency_code="097",
        funding_agency_name="Department of Defense",
        funding_sub_agency_code="1700",
        funding_sub_agency_name="DEPT OF THE NAVY",
        funding_office_code="N00024",
        funding_office_name="NAVSEA",
        naics_code="541330",
        naics_description="Engineering Services",
        product_or_service_code="R425",
        product_or_service_code_description="Support",
        recipient_country_code="USA",
        recipient_state_code="VA",
        recipient_city_name="Arlington",
        recipient_zip_4_code="22202",
        primary_place_of_performance_country_code="USA",
        primary_place_of_performance_state_code="MD",
        primary_place_of_performance_city_name="Bethesda",
        primary_place_of_performance_zip_4="20814",
        parent_award_id_piid="PARENT1",
        parent_award_agency_id="9700",
    )
    rows = [
        blank_projected_row(
            contract_transaction_unique_key="T_SHARED",
            contract_award_unique_key="A_SHARED",
            award_id_piid="PIID-SHARED",
            action_date="2025-06-01",
            federal_action_obligation="100",
            total_dollars_obligated="100",
            current_total_value_of_award="100",
            potential_total_value_of_award="100",
            **shared,
        ),
        blank_projected_row(
            contract_transaction_unique_key="T_OTHER",
            contract_award_unique_key="A_OTHER",
            award_id_piid="PIID-OTHER",
            action_date="2025-06-02",
            federal_action_obligation="50",
            total_dollars_obligated="50",
            current_total_value_of_award="50",
            potential_total_value_of_award="50",
            recipient_uei="UEI_ALPHA",
            recipient_name="Alpha Corp",
            awarding_agency_code="097",
            awarding_agency_name="Department of Defense",
            awarding_sub_agency_code="5700",
            awarding_sub_agency_name="DEPT OF THE ARMY",
            awarding_office_code="W15P7T",
            awarding_office_name="ACC",
            funding_agency_code="097",
            funding_agency_name="Department of Defense",
            funding_sub_agency_code="5700",
            funding_sub_agency_name="DEPT OF THE ARMY",
            funding_office_code="W15P7T",
            funding_office_name="ACC",
            naics_code="336411",
            # Description absent → classification label falls back to code
            product_or_service_code="1510",
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
            contract_transaction_unique_key="T_SPARSE",
            contract_award_unique_key="A_SPARSE",
            award_id_piid="PIID-SPARSE",
            action_date="2025-06-03",
            federal_action_obligation="10",
            total_dollars_obligated="10",
            current_total_value_of_award="10",
            potential_total_value_of_award="10",
            recipient_uei="UEI_SPARSE",
            recipient_name="Sparse LLC",
            # No agency / office / classification / IDV / locations
        ),
    ]
    csv_path = write_projected_csv(tmp_path / "traverse.csv", rows)
    data_root = tmp_path / "data"
    materialize(
        [csv_path],
        out=data_root,
        run_id="20260914T200000Z_abcdef",
        allow_rejects=True,
    )
    return data_root


# === Core Behavior ===

def test_role_preservation_same_agency_awarding_and_funding(
    traverse_data_root: Path,
) -> None:
    dod = agency_id(tier=AgencyTier.TOPTIER, code="097")
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED"])
        result = ds.traverse_relationships(sel, include={EntityKind.AGENCY})
        matching = [
            e
            for e in result.entities
            if e.entity_id == dod and e.agency_tier is AgencyTier.TOPTIER
        ]
        roles = {e.role for e in matching}
        assert roles == {RelationRole.AWARDING, RelationRole.FUNDING}
        assert len(matching) == 2

def test_dedupes_shared_recipient_across_awards(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED", "A_OTHER"])
        result = ds.traverse_relationships(sel, include={EntityKind.RECIPIENT})
        recipients = [e for e in result.entities if e.kind is EntityKind.RECIPIENT]
        assert [e.entity_id for e in recipients] == ["UEI_ALPHA"]
        assert recipients[0].label == "Alpha Corp"
        assert recipients[0].role is None

def test_null_optional_relationships_omitted(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SPARSE"])
        result = ds.traverse_relationships(sel)
        kinds = {e.kind for e in result.entities}
        assert kinds == {EntityKind.RECIPIENT}
        assert result.entities[0].entity_id == "UEI_SPARSE"

def test_include_none_all_vs_empty_vs_subset(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED"])
        all_kinds = {e.kind for e in ds.traverse_relationships(sel).entities}
        assert EntityKind.RECIPIENT in all_kinds
        assert EntityKind.AGENCY in all_kinds
        assert EntityKind.IDV in all_kinds

        assert ds.traverse_relationships(sel, include=()).entities == ()

        only = ds.traverse_relationships(sel, include={EntityKind.IDV})
        assert all(e.kind is EntityKind.IDV for e in only.entities)
        assert len(only.entities) == 1
        expected_idv = idv_id(piid="PARENT1", award_key_agency_id="9700")
        assert only.entities[0].entity_id == expected_idv
        assert only.entities[0].label == "PARENT1"
        assert only.entities[0].idv_agency_id == "9700"
        assert only.entities[0].role is None

def test_include_rejects_non_entity_kind(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED"])
        with pytest.raises(ValueError, match="EntityKind"):
            ds.traverse_relationships(sel, include=["recipient"])  # type: ignore[list-item]

def test_sort_order_kind_role_tier_entity_id(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED", "A_OTHER"])
        entities = ds.traverse_relationships(sel).entities
        kind_rank = {k: i for i, k in enumerate(EntityKind)}
        role_rank = {r: i for i, r in enumerate(RelationRole)}
        tier_rank = {t: i for i, t in enumerate(AgencyTier)}

        def key(e):  # Mirrors contract sort
            return (
                kind_rank[e.kind],
                -1 if e.role is None else role_rank[e.role],
                -1 if e.agency_tier is None else tier_rank[e.agency_tier],
                e.entity_id,
            )

        assert list(entities) == sorted(entities, key=key)

def test_location_roles_and_classification_labels(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards(["A_SHARED", "A_OTHER"])
        result = ds.traverse_relationships(
            sel,
            include={EntityKind.LOCATION, EntityKind.CLASSIFICATION},
        )
        loc_roles = {
            e.role for e in result.entities if e.kind is EntityKind.LOCATION
        }
        assert RelationRole.RECIPIENT in loc_roles
        assert RelationRole.PLACE_OF_PERFORMANCE in loc_roles
        for loc in result.entities:
            if loc.kind is EntityKind.LOCATION:
                assert loc.label is None
                assert loc.granularity

        eng = classification_id(ClassificationKind.NAICS, "541330")
        eng_ent = next(e for e in result.entities if e.entity_id == eng)
        assert eng_ent.label == "Engineering Services"
        assert eng_ent.code == "541330"
        assert eng_ent.classification_kind is ClassificationKind.NAICS

        bare = classification_id(ClassificationKind.NAICS, "336411")
        bare_ent = next(e for e in result.entities if e.entity_id == bare)
        assert bare_ent.description is None
        assert bare_ent.label == "336411"


# === Session / Empty / Handoff ===

def test_empty_selection_returns_empty(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds:
        sel = ds.select_awards([])
        assert sel.count == 0
        assert ds.traverse_relationships(sel).entities == ()

def test_stale_selection_rejected(traverse_data_root: Path) -> None:
    with ProcurementDataset.open(traverse_data_root) as ds1:
        sel = ds1.select_awards(["A_SHARED"])
    with ProcurementDataset.open(traverse_data_root) as ds2:
        with pytest.raises(StaleSelectionError):
            ds2.traverse_relationships(sel)

def test_handoff_into_structured_filters(traverse_data_root: Path) -> None:
    navy = agency_id(tier=AgencyTier.SUBTIER, code="1700")
    navsea = office_id(sub_agency_code="1700", office_code="N00024")
    assert navsea is not None
    with ProcurementDataset.open(traverse_data_root) as ds:
        seed = ds.select_awards(["A_SHARED"])
        related = ds.traverse_relationships(seed)

        recipients = [
            e.entity_id for e in related.entities if e.kind is EntityKind.RECIPIENT
        ]
        handoff = ds.resolve_awards(AwardFilters(recipient_ids=recipients))
        assert "A_SHARED" in ds.award_ids(handoff)
        assert "A_OTHER" in ds.award_ids(handoff)

        agencies = [
            e.entity_id
            for e in related.entities
            if e.kind is EntityKind.AGENCY
            and e.role is RelationRole.AWARDING
            and e.agency_tier is AgencyTier.SUBTIER
            and e.entity_id == navy
        ]
        assert agencies
        navy_awards = ds.resolve_awards(AwardFilters(awarding_sub_agency_ids=agencies))
        assert ds.award_ids(navy_awards) == frozenset({"A_SHARED"})

        pops = [
            e.entity_id
            for e in related.entities
            if e.kind is EntityKind.LOCATION
            and e.role is RelationRole.PLACE_OF_PERFORMANCE
        ]
        pop_awards = ds.resolve_awards(
            AwardFilters(
                location=LocationFilter(
                    role=LocationRole.PLACE_OF_PERFORMANCE,
                    location_ids=pops,
                )
            )
        )
        assert "A_SHARED" in ds.award_ids(pop_awards)
