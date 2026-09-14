# tests/cy_th/query/test_resolve.py

"""Tests for `resolve_awards` filter semantics."""

# === Imports ===

from __future__ import annotations
import pytest

from cy_th.query.dataset import ProcurementDataset
from cy_th.query.types import AwardFilters, LocationFilter, LocationRole
from cy_th.schema.enums import AgencyTier, ClassificationKind
from cy_th.schema.keys import agency_id, classification_id, office_id


# === List Semantics ===

def test_unconstrained_returns_all_awards(dataset: ProcurementDataset) -> None:
    with dataset:
        assert dataset.resolve_awards() == frozenset({"A1", "A2", "A3", "A4"})

def test_empty_list_means_zero_matches(dataset: ProcurementDataset) -> None:
    with dataset:
        assert dataset.resolve_awards(AwardFilters(recipient_ids=[])) == frozenset()
        assert dataset.resolve_awards(AwardFilters(award_ids=[])) == frozenset()

def test_award_ids_and_with_other_filters(dataset: ProcurementDataset) -> None:
    with dataset:
        got = dataset.resolve_awards(
            AwardFilters(
                award_ids=["A1", "A2", "A3"],
                recipient_ids=["UEI_ALPHA"],
            )
        )
        assert got == frozenset({"A1", "A3"})


# === Topology Filters ===

def test_recipient_and_agency_office_classification(dataset: ProcurementDataset) -> None:
    with dataset:
        dod = agency_id(tier=AgencyTier.TOPTIER, code="097")
        navy = agency_id(tier=AgencyTier.SUBTIER, code="1700")
        navsea = office_id(sub_agency_code="1700", office_code="N00024")
        assert navsea is not None
        naics = classification_id(ClassificationKind.NAICS, "541330")
        psc = classification_id(ClassificationKind.PSC, "R425")

        assert dataset.resolve_awards(AwardFilters(recipient_ids=["UEI_BETA"])) == frozenset(
            {"A2"}
        )
        assert dataset.resolve_awards(AwardFilters(awarding_agency_ids=[dod])) == frozenset(
            {"A1", "A2", "A3", "A4"}
        )
        assert dataset.resolve_awards(
            AwardFilters(awarding_sub_agency_ids=[navy])
        ) == frozenset({"A1", "A3"})
        assert dataset.resolve_awards(
            AwardFilters(awarding_office_ids=[navsea])
        ) == frozenset({"A1", "A3"})
        assert dataset.resolve_awards(AwardFilters(naics_ids=[naics])) == frozenset(
            {"A1", "A3"}
        )
        assert dataset.resolve_awards(AwardFilters(psc_ids=[psc])) == frozenset({"A1", "A3"})

def test_funding_office_distinct_from_awarding(dataset: ProcurementDataset) -> None:
    with dataset:
        army_office = office_id(sub_agency_code="5700", office_code="W15P7T")
        assert army_office is not None
        assert dataset.resolve_awards(
            AwardFilters(funding_office_ids=[army_office])
        ) == frozenset({"A2"})
        assert dataset.resolve_awards(
            AwardFilters(awarding_office_ids=[army_office])
        ) == frozenset({"A2"})


# === Location ===

def test_location_role_is_not_silently_ored(dataset: ProcurementDataset) -> None:
    with dataset:
        pop_va = dataset.resolve_awards(
            AwardFilters(
                location=LocationFilter(
                    role=LocationRole.PLACE_OF_PERFORMANCE,
                    state_code="VA",
                )
            )
        )
        rec_va = dataset.resolve_awards(
            AwardFilters(
                location=LocationFilter(
                    role=LocationRole.RECIPIENT,
                    state_code="VA",
                )
            )
        )
        assert pop_va == frozenset({"A1"})
        assert rec_va == frozenset({"A1", "A2", "A3"})

def test_location_structured_city_normalized(dataset: ProcurementDataset) -> None:
    with dataset:
        got = dataset.resolve_awards(
            AwardFilters(
                location=LocationFilter(
                    role=LocationRole.PLACE_OF_PERFORMANCE,
                    state_code="MD",
                    city_name=" BETHESDA ",
                )
            )
        )
        assert got == frozenset({"A2"})

def test_location_ids_empty_zero_matches(dataset: ProcurementDataset) -> None:
    with dataset:
        assert (
            dataset.resolve_awards(
                AwardFilters(
                    location=LocationFilter(
                        role=LocationRole.PLACE_OF_PERFORMANCE,
                        location_ids=[],
                    )
                )
            )
            == frozenset()
        )

def test_location_filter_requires_predicates(dataset: ProcurementDataset) -> None:
    with dataset:
        with pytest.raises(ValueError, match="LocationFilter requires"):
            dataset.resolve_awards(
                AwardFilters(location=LocationFilter(role=LocationRole.RECIPIENT))
            )
