# tests/cy_th/materialize/test_txn_refs.py

"""Tests for `TransactionFact` + ref table materialization."""

# === Imports ===

from __future__ import annotations
from pathlib import Path

from cy_th.materialize.load import connect_staging, load_projected_csvs
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_LOCATIONS,
    TABLE_OFFICES,
    TABLE_RECIPIENTS,
    materialize_references,
)
from cy_th.materialize.transactions import TABLE_TRANSACTIONS, materialize_transactions
from cy_th.materialize.validate import validate_and_dedupe
from cy_th.schema.enums import AgencyTier
from cy_th.schema.keys import agency_id, location_id, office_id
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Helpers ===

def _stage(tmp_path: Path, rows: list[dict[str, str]]):
    csv_path = write_projected_csv(tmp_path / "in.csv", rows)
    conn = connect_staging(tmp_path / "stage.duckdb")
    load_projected_csvs(conn, [csv_path])
    validate_and_dedupe(conn)
    return conn


# === TransactionFact ===

def test_transaction_fact_maps_identity_columns(tmp_path: Path) -> None:
    conn = _stage(
        tmp_path,
        [
            blank_projected_row(
                contract_transaction_unique_key="TXN_MAP",
                contract_award_unique_key="AWD_MAP",
                federal_action_obligation="3.25",
            ),
        ],
    )
    assert materialize_transactions(conn) == 1
    row = conn.execute(
        f"""
        SELECT transaction_id, award_id, federal_action_obligation
        FROM "{TABLE_TRANSACTIONS}"
        """
    ).fetchone()
    assert row is not None
    assert row[0] == "TXN_MAP"
    assert row[1] == "AWD_MAP"
    assert float(row[2]) == 3.25


# === Refs ===

def test_latest_nonempty_descriptor_and_tie_break(tmp_path: Path) -> None:
    conn = _stage(
        tmp_path,
        [
            blank_projected_row(
                contract_transaction_unique_key="T1",
                action_date="2025-01-01",
                awarding_agency_code="097",
                awarding_agency_name="OLD",
            ),
            blank_projected_row(
                contract_transaction_unique_key="T2",
                action_date="2025-06-01",
                awarding_agency_code="097",
                awarding_agency_name="",
            ),
            blank_projected_row(
                contract_transaction_unique_key="T3",
                action_date="2025-12-01",
                awarding_agency_code="097",
                awarding_agency_name="NEW",
            ),
            blank_projected_row(
                contract_transaction_unique_key="T5",
                action_date="2025-03-01",
                awarding_agency_code="098",
                awarding_agency_name="B_NAME",
            ),
            blank_projected_row(
                contract_transaction_unique_key="T4",
                action_date="2025-03-01",
                awarding_agency_code="098",
                awarding_agency_name="A_NAME",
            ),
        ],
    )
    materialize_transactions(conn)
    materialize_references(conn)

    name_097_row = conn.execute(
        f'SELECT name FROM "{TABLE_AGENCIES}" WHERE agency_id = ?',
        [agency_id(tier=AgencyTier.TOPTIER, code="097")],
    ).fetchone()
    assert name_097_row is not None
    assert name_097_row[0] == "NEW"

    name_098_row = conn.execute(
        f'SELECT name FROM "{TABLE_AGENCIES}" WHERE agency_id = ?',
        [agency_id(tier=AgencyTier.TOPTIER, code="098")],
    ).fetchone()
    assert name_098_row is not None
    assert name_098_row[0] == "A_NAME"

def test_office_skip_empty_location_and_recipient_stubs(tmp_path: Path) -> None:
    conn = _stage(
        tmp_path,
        [
            blank_projected_row(
                contract_transaction_unique_key="O1",
                awarding_sub_agency_code="1700",
                awarding_office_code="",
                awarding_office_name="SHOULD_SKIP",
                recipient_uei="CHILD_UEI",
                recipient_name="Child Co",
                recipient_parent_uei="PARENT_UEI",
                primary_place_of_performance_country_code="USA",
                primary_place_of_performance_state_code="VA",
                primary_place_of_performance_city_name="Arlington",
                primary_place_of_performance_zip_4="22202",
            ),
            blank_projected_row(
                contract_transaction_unique_key="O2",
                action_date="2025-02-01",
                recipient_uei="PARENT_UEI",
                recipient_name="Parent Co",
            ),
            blank_projected_row(
                contract_transaction_unique_key="O3",
                action_date="2025-03-01",
                recipient_uei="OTHER_UEI",
                recipient_name="Other",
                recipient_parent_uei="STUB_ONLY_UEI",
            ),
        ],
    )
    materialize_transactions(conn)
    refs = materialize_references(conn)

    office_count = conn.execute(
        f'SELECT COUNT(*) FROM "{TABLE_OFFICES}" WHERE sub_agency_code = ?',
        ["1700"],
    ).fetchone()
    assert office_count is not None
    assert office_count[0] == 0

    pop_id = location_id(
        country_code="USA",
        state_code="VA",
        city_name="Arlington",
        zip_code="22202",
    )
    assert pop_id is not None
    loc_count = conn.execute(
        f'SELECT COUNT(*) FROM "{TABLE_LOCATIONS}" WHERE location_id = ?',
        [pop_id],
    ).fetchone()
    assert loc_count is not None
    assert loc_count[0] == 1

    empty_count = conn.execute(
        f"""
        SELECT COUNT(*) FROM "{TABLE_LOCATIONS}"
        WHERE granularity = 'empty' OR granularity IS NULL OR granularity = ''
        """
    ).fetchone()
    assert empty_count is not None
    assert empty_count[0] == 0

    parent = conn.execute(
        f'SELECT name, parent_uei FROM "{TABLE_RECIPIENTS}" WHERE uei = ?',
        ["PARENT_UEI"],
    ).fetchone()
    assert parent == ("Parent Co", None)

    stub = conn.execute(
        f'SELECT name, parent_uei FROM "{TABLE_RECIPIENTS}" WHERE uei = ?',
        ["STUB_ONLY_UEI"],
    ).fetchone()
    assert stub == (None, None)
    assert refs.recipients >= 3

def test_office_id_parity_when_present(tmp_path: Path) -> None:
    conn = _stage(
        tmp_path,
        [
            blank_projected_row(
                awarding_sub_agency_code="1700",
                awarding_office_code="N00019",
                awarding_office_name="NAVAIR",
            ),
        ],
    )
    materialize_references(conn)
    expected = office_id(sub_agency_code="1700", office_code="N00019")
    got = conn.execute(
        f'SELECT office_id FROM "{TABLE_OFFICES}"'
    ).fetchone()
    assert got is not None
    assert got[0] == expected
