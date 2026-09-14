# cy_th/materialize/awards.py

"""DuckDB AwardRecord reduce from `staging_valid`.

Topology/semantics come from one projection row per award (`action_date DESC`, `transaction_id ASC`). Money snapshot uses eligible-latest-day rule (test oracle / reference implementation in `schema/snapshot.py`).
"""

# === Imports ===

from __future__ import annotations
from typing import Final
import duckdb

from cy_th.materialize.references import _require_table
from cy_th.materialize.validate import TABLE_VALID, TXN_ID_COL, _SQL_LIST_SEP
from cy_th.schema.db_types import quote_ident
from cy_th.schema.enums import (
    AgencyTier,
    ClassificationKind,
    SnapshotSource,
    SnapshotStatus,
)


# === Constants ===

TABLE_AWARDS: Final[str] = "award_record"
"""Canonical Award rows (`AwardRecord`)."""

_AWARD_ID: Final[str] = "contract_award_unique_key"
_ACTION: Final[str] = "action_date"
_TXN_NUM: Final[str] = "transaction_number"

_TOPTIER: Final[str] = AgencyTier.TOPTIER.value
_SUBTIER: Final[str] = AgencyTier.SUBTIER.value
_NAICS: Final[str] = ClassificationKind.NAICS.value
_PSC: Final[str] = ClassificationKind.PSC.value

_DEFENSIBLE: Final[str] = SnapshotStatus.DEFENSIBLE.value
_NOT_OBSERVED: Final[str] = SnapshotStatus.NOT_OBSERVED.value
_REQUIRES: Final[str] = SnapshotStatus.REQUIRES_ENRICHMENT.value
_SRC_TXN: Final[str] = SnapshotSource.TRANSACTION.value
_SRC_NONE: Final[str] = SnapshotSource.NONE.value


# === Materialize ===

def materialize_awards(conn: duckdb.DuckDBPyConnection) -> int:
    """Build `award_record` from `staging_valid`.

    #### Returns:
		Award row count

    Raises `ValueError` if `staging_valid` is missing.
    """

    _require_table(conn, TABLE_VALID)

    q = quote_ident
    src = q(TABLE_VALID)
    out = q(TABLE_AWARDS)
    txn = q(TXN_ID_COL)
    award = q(_AWARD_ID)
    action = q(_ACTION)
    txn_num = q(_TXN_NUM)

    topology_fks = _topology_select_sql(alias="t")
    money_select = _money_select_sql(alias="m")

    conn.execute(f"DROP TABLE IF EXISTS {out}")
    conn.execute(
        f"""
        CREATE TABLE {out} AS
        WITH topology AS (
          SELECT *
          FROM (
            SELECT
              s.*,
              ROW_NUMBER() OVER (
                PARTITION BY s.{award}
                ORDER BY s.{action} DESC, s.{txn} ASC
              ) AS {q('_topo_rn')}
            FROM {src} AS s
          ) ranked
          WHERE {q('_topo_rn')} = 1
        ),
        eligible AS (
          SELECT *
          FROM {src}
          WHERE {txn_num} IS NULL OR {txn_num} = '0'
        ),
        latest_eligible AS (
          SELECT
            {award} AS {q('award_id')},
            MAX({action}) AS {q('latest_date')}
          FROM eligible
          GROUP BY {award}
        ),
        candidates AS (
          SELECT e.*
          FROM eligible AS e
          INNER JOIN latest_eligible AS le
            ON e.{award} = le.{q('award_id')}
           AND e.{action} = le.{q('latest_date')}
        ),
        money AS (
          SELECT
            c.{award} AS {q('award_id')},
            COUNT(*) AS {q('candidate_count')},
            COUNT(DISTINCT concat_ws(
              chr(31),
              coalesce(CAST(c.{q('total_dollars_obligated')} AS VARCHAR), ''),
              coalesce(CAST(c.{q('current_total_value_of_award')} AS VARCHAR), ''),
              coalesce(CAST(c.{q('potential_total_value_of_award')} AS VARCHAR), '')
            )) AS {q('distinct_triples')},
            ANY_VALUE(c.{q('total_dollars_obligated')})
              AS {q('observed_total_obligation')},
            ANY_VALUE(c.{q('current_total_value_of_award')})
              AS {q('observed_current_value')},
            ANY_VALUE(c.{q('potential_total_value_of_award')})
              AS {q('observed_potential_value')},
            MIN(c.{txn}) AS {q('snapshot_transaction_id')}
          FROM candidates AS c
          GROUP BY c.{award}
        ),
        awards_with_txns AS (
          SELECT DISTINCT {award} AS {q('award_id')} FROM {src}
        ),
        money_resolved AS (
          SELECT
            a.{q('award_id')} AS {q('award_id')},
            s.{q('snapshot_status')} AS {q('snapshot_status')},
            CASE
              WHEN s.{q('snapshot_status')} = '{_REQUIRES}' THEN '{_SRC_NONE}'
              ELSE '{_SRC_TXN}'
            END AS {q('snapshot_source')},
            CASE
              WHEN s.{q('snapshot_status')} = '{_DEFENSIBLE}'
              THEN m.{q('observed_total_obligation')}
            END AS {q('observed_total_obligation')},
            CASE
              WHEN s.{q('snapshot_status')} = '{_DEFENSIBLE}'
              THEN m.{q('observed_current_value')}
            END AS {q('observed_current_value')},
            CASE
              WHEN s.{q('snapshot_status')} = '{_DEFENSIBLE}'
              THEN m.{q('observed_potential_value')}
            END AS {q('observed_potential_value')},
            CASE
              WHEN s.{q('snapshot_status')} = '{_DEFENSIBLE}'
              THEN m.{q('snapshot_transaction_id')}
            END AS {q('snapshot_transaction_id')}
          FROM awards_with_txns AS a
          LEFT JOIN money AS m
            ON a.{q('award_id')} = m.{q('award_id')}
          CROSS JOIN LATERAL (
            SELECT
              CASE
                WHEN m.{q('award_id')} IS NULL THEN '{_REQUIRES}'
                WHEN m.{q('distinct_triples')} > 1 THEN '{_REQUIRES}'
                WHEN m.{q('observed_total_obligation')} IS NULL
                 AND m.{q('observed_current_value')} IS NULL
                 AND m.{q('observed_potential_value')} IS NULL
                  THEN '{_NOT_OBSERVED}'
                WHEN m.{q('observed_total_obligation')} IS NULL
                  OR m.{q('observed_current_value')} IS NULL
                  OR m.{q('observed_potential_value')} IS NULL
                  THEN '{_REQUIRES}'
                ELSE '{_DEFENSIBLE}'
              END AS {q('snapshot_status')}
          ) AS s
        )
        SELECT
          {topology_fks},
          {money_select},
          CAST(NULL AS DATE) AS {q('date_signed')}
        FROM topology AS t
        INNER JOIN money_resolved AS m
          ON t.{award} = m.{q('award_id')}
        """
    )

    count_row = conn.execute(f"SELECT COUNT(*) FROM {out}").fetchone()
    assert count_row is not None
    return int(count_row[0])


# === SQL Fragments ===

def _location_id_expr(
    *,
    country: str,
    state: str,
    county: str,
    city: str,
    zip_col: str,
    alias: str,
) -> str:
    """SHA-256 location ID matching `keys.location_id`, else NULL if empty geo."""

    q = quote_ident
    a = q(alias)
    country_n = f"coalesce({a}.{q(country)}, '')"
    state_n = f"coalesce({a}.{q(state)}, '')"
    county_n = f"coalesce({a}.{q(county)}, '')"
    city_n = f"coalesce(lower({a}.{q(city)}), '')"
    zip_n = f"coalesce({a}.{q(zip_col)}, '')"
    payload = (
        f"concat_ws(chr(31), {country_n}, {state_n}, {county_n}, {city_n}, {zip_n})"  # chr(31) is unit separator
    )
    nonempty = (
        f"({country_n} <> '' OR {state_n} <> '' OR {county_n} <> '' "
        f"OR {city_n} <> '' OR {zip_n} <> '')"
    )
    return f"CASE WHEN {nonempty} THEN sha256({payload}) END"

def _topology_select_sql(*, alias: str) -> str:
    """Award identity, role FKs, and semantics from the topology row."""

    q = quote_ident
    a = q(alias)

    def agency(tier: str, code_col: str) -> str:
        """Agency ID from code (NULL → NULL), else prefixed with tier."""
        
        return (
            f"CASE WHEN {a}.{q(code_col)} IS NOT NULL "
            f"THEN '{tier}:' || {a}.{q(code_col)} END"
        )

    def office(sub_col: str, office_col: str) -> str:
        """Office ID from sub-agency + office codes (NULL → NULL), else combined."""
        
        return (
            f"CASE WHEN {a}.{q(office_col)} IS NOT NULL "
            f"AND {a}.{q(sub_col)} IS NOT NULL "
            f"THEN {a}.{q(sub_col)} || ':' || {a}.{q(office_col)} END"
        )

    recipient_loc = _location_id_expr(
        country="recipient_country_code",
        state="recipient_state_code",
        county="prime_award_transaction_recipient_county_fips_code",
        city="recipient_city_name",
        zip_col="recipient_zip_4_code",
        alias=alias,
    )
    pop_loc = _location_id_expr(
        country="primary_place_of_performance_country_code",
        state="primary_place_of_performance_state_code",
        county="prime_award_transaction_place_of_performance_county_fips_code",
        city="primary_place_of_performance_city_name",
        zip_col="primary_place_of_performance_zip_4",
        alias=alias,
    )

    # Build final SELECT list
    parts = [
        f"{a}.{q(_AWARD_ID)} AS {q('award_id')}",
        f"{a}.{q('award_id_piid')} AS {q('piid')}",
        f"{a}.{q('award_type_code')} AS {q('award_type_code')}",
        f"{a}.{q('recipient_uei')} AS {q('recipient_id')}",
        f"{agency(_TOPTIER, 'awarding_agency_code')} AS {q('awarding_agency_id')}",
        f"{agency(_SUBTIER, 'awarding_sub_agency_code')} AS {q('awarding_sub_agency_id')}",
        f"{office('awarding_sub_agency_code', 'awarding_office_code')} AS {q('awarding_office_id')}",
        f"{agency(_TOPTIER, 'funding_agency_code')} AS {q('funding_agency_id')}",
        f"{agency(_SUBTIER, 'funding_sub_agency_code')} AS {q('funding_sub_agency_id')}",
        f"{office('funding_sub_agency_code', 'funding_office_code')} AS {q('funding_office_id')}",
        (
            f"CASE WHEN {a}.{q('parent_award_id_piid')} IS NOT NULL "
            f"AND {a}.{q('parent_award_agency_id')} IS NOT NULL "
            f"THEN 'CONT_IDV_' || {a}.{q('parent_award_id_piid')} || '_' "
            f"|| {a}.{q('parent_award_agency_id')} END AS {q('parent_idv_id')}"
        ),
        (
            f"CASE WHEN {a}.{q('naics_code')} IS NOT NULL "
            f"THEN '{_NAICS}:' || {a}.{q('naics_code')} END AS {q('naics_id')}"
        ),
        (
            f"CASE WHEN {a}.{q('product_or_service_code')} IS NOT NULL "
            f"THEN '{_PSC}:' || {a}.{q('product_or_service_code')} END AS {q('psc_id')}"
        ),
        f"{recipient_loc} AS {q('recipient_location_id')}",
        f"{pop_loc} AS {q('place_of_performance_id')}",
        (
            f"{a}.{q('prime_award_base_transaction_description')} "
            f"AS {q('base_description')}"
        ),
        f"{a}.{q('usaspending_permalink')} AS {q('usaspending_permalink')}",
        f"{a}.{q('period_of_performance_start_date')} AS {q('pop_start')}",
        f"{a}.{q('period_of_performance_current_end_date')} AS {q('pop_end')}",
        f"{a}.{q(TXN_ID_COL)} AS {q('projection_transaction_id')}",
    ]
    return _SQL_LIST_SEP.join(parts)

def _money_select_sql(*, alias: str) -> str:
    """Money snapshot columns from `money_resolved`."""

    q = quote_ident
    a = q(alias)
    cols = (
        "observed_total_obligation",
        "observed_current_value",
        "observed_potential_value",
        "snapshot_status",
        "snapshot_source",
        "snapshot_transaction_id",
    )
    return _SQL_LIST_SEP.join(f"{a}.{q(c)} AS {q(c)}" for c in cols)
