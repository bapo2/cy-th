# tests/cy_th/schema/test_keys.py

"""Tests for deterministic identity helpers."""

# === Imports ===

import pytest

from cy_th.schema.enums import AgencyTier, ClassificationKind
from cy_th.schema.keys import (
    agency_id,
    classification_id,
    idv_id,
    location_granularity,
    location_id,
    normalize_city_name,
    office_id,
)


# === Synthetic Guards (Invalid Inputs) ===

def test_agency_id_form() -> None:
    assert agency_id(tier=AgencyTier.TOPTIER, code="097") == "toptier:097"
    assert agency_id(tier=AgencyTier.SUBTIER, code=" 97AS ") == "subtier:97AS"

def test_agency_id_rejects_blank_code() -> None:
    with pytest.raises(ValueError):
        agency_id(tier=AgencyTier.TOPTIER, code=" ")

def test_classification_and_idv_forms() -> None:
    assert classification_id(ClassificationKind.NAICS, "541330") == "NAICS:541330"
    assert classification_id(ClassificationKind.PSC, "R425") == "PSC:R425"
    assert idv_id(piid="SPE30023DS758", award_key_agency_id="9700") == ("CONT_IDV_SPE30023DS758_9700")

def test_office_id_skips_blank_office_code() -> None:
    assert office_id(sub_agency_code="97AS", office_code="SPE3SU") == "97AS:SPE3SU"
    assert office_id(sub_agency_code="97AS", office_code="") is None
    with pytest.raises(ValueError):
        office_id(sub_agency_code="", office_code="X")

def test_location_normalization_is_stable() -> None:
    a = location_id(country_code="USA", state_code="VA", city_name="Charlottesville")
    b = location_id(country_code="USA", state_code="VA", city_name=" charlottesville ")
    assert a == b
    assert normalize_city_name(" Charlottesville ") == "charlottesville"
    assert location_granularity(country_code="USA", state_code="VA", city_name="Charlottesville") == "country/state/city"


# === Real Rows ===

def test_keys_from_real_rows_keep_agency_namespaces(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    """AgencyRef codes stay in the `097` namespace; IDV keys keep `9700`."""

    saw_dod = False
    for row in prime_txn_sample:
        code = (row.get("awarding_agency_code") or "").strip()
        if code == "097":
            saw_dod = True
            assert agency_id(tier=AgencyTier.TOPTIER, code=code) == "toptier:097"

        piid = (row.get("parent_award_id_piid") or "").strip()
        award_key_agency_id = (row.get("parent_award_agency_id") or "").strip()
        if piid and award_key_agency_id:
            generated = idv_id(piid=piid, award_key_agency_id=award_key_agency_id)
            assert generated.endswith(f"_{award_key_agency_id}")
            assert ":097" not in generated

    assert saw_dod, "expected at least one awarding_agency_code=097 in sample"

def test_office_and_classification_from_real_rows(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    offices: set[str] = set()
    classifications: set[str] = set()
    for row in prime_txn_sample:
        oid = office_id(
            sub_agency_code=row.get("awarding_sub_agency_code") or "",
            office_code=row.get("awarding_office_code") or "",
        )
        if oid is not None:
            offices.add(oid)
        if (row.get("naics_code") or "").strip():
            classifications.add(
                classification_id(ClassificationKind.NAICS, row["naics_code"])
            )
        if (row.get("product_or_service_code") or "").strip():
            classifications.add(
                classification_id(ClassificationKind.PSC, row["product_or_service_code"])
            )

    assert offices, "expected at least one awarding office in sample"
    assert any(c.startswith("NAICS:") for c in classifications)
    assert any(c.startswith("PSC:") for c in classifications)

def test_location_ids_from_real_recipient_fields(
    prime_txn_sample: list[dict[str, str]],
) -> None:
    ids = {
        location_id(
            country_code=row.get("recipient_country_code"),
            state_code=row.get("recipient_state_code"),
            county_fips=row.get("prime_award_transaction_recipient_county_fips_code"),
            city_name=row.get("recipient_city_name"),
            zip_code=row.get("recipient_zip_4_code"),
        )
        for row in prime_txn_sample
    }
    assert len(ids) >= 1
    assert all(len(i) == 64 for i in ids)  # SHA-256 hex digests (64 chars)
