# cy_th/materialize/references.py

"""Build compact reference tables from `staging_valid`.

#### Rules:
	- Descriptors are latest non-empty by `action_date`, tie-break via `transaction_id ASC`
	- Parent UEI stubs (`name` / `parent_uei` null) only when never observed as a recipient
	- Offices require both sub-agency and office codes (blank office → no row)
	- Empty geo tuples → no `LocationRef`
	- IDV rows are stubs (`hydration_status = stub`) from child parent fields
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from typing import Final
import duckdb

from cy_th.materialize.validate import TABLE_VALID, TXN_ID_COL, _SQL_LIST_SEP
from cy_th.schema.db_types import quote_ident
from cy_th.schema.enums import AgencyTier, ClassificationKind, HydrationStatus


# === Constants ===

TABLE_AGENCIES: Final[str] = "ref_agencies"
TABLE_OFFICES: Final[str] = "ref_offices"
TABLE_RECIPIENTS: Final[str] = "ref_recipients"
TABLE_CLASSIFICATIONS: Final[str] = "ref_classifications"
TABLE_IDVS: Final[str] = "ref_idvs"
TABLE_LOCATIONS: Final[str] = "ref_locations"

_ACTION: Final[str] = "action_date"
_TXN: Final[str] = TXN_ID_COL

_TOPTIER: Final[str] = AgencyTier.TOPTIER.value
_SUBTIER: Final[str] = AgencyTier.SUBTIER.value
_NAICS: Final[str] = ClassificationKind.NAICS.value
_PSC: Final[str] = ClassificationKind.PSC.value
_STUB: Final[str] = HydrationStatus.STUB.value


# === Results ===

@dataclass(frozen=True, slots=True)
class RefMaterializeResult:
    """Row counts for each ref table."""

    agencies: int
    offices: int
    recipients: int
    classifications: int
    idvs: int
    locations: int


# === Materialize ===

def materialize_references(conn: duckdb.DuckDBPyConnection) -> RefMaterializeResult:
    """Build all `ref_*` tables from `staging_valid`.

    Raises `ValueError` if `staging_valid` is missing.
    """

    _require_table(conn, TABLE_VALID)

    agencies = _materialize_agencies(conn)
    offices = _materialize_offices(conn)
    recipients = _materialize_recipients(conn)
    classifications = _materialize_classifications(conn)
    idvs = _materialize_idvs(conn)
    locations = _materialize_locations(conn)

    return RefMaterializeResult(
        agencies=agencies,
        offices=offices,
        recipients=recipients,
        classifications=classifications,
        idvs=idvs,
        locations=locations,
    )


# === Agencies ===

def _materialize_agencies(conn: duckdb.DuckDBPyConnection) -> int:
    """Union awarding/funding × toptier/subtier, then latest non-empty name."""

    q = quote_ident
    src = q(TABLE_VALID)
    observations = f"""
        SELECT
          '{_TOPTIER}:' || {q('awarding_agency_code')} AS {q('agency_id')},
          '{_TOPTIER}' AS {q('tier')},
          {q('awarding_agency_code')} AS {q('code')},
          {q('awarding_agency_name')} AS {q('name')},
          {q(_ACTION)} AS {q(_ACTION)},
          {q(_TXN)} AS {q(_TXN)}
        FROM {src}
        WHERE {q('awarding_agency_code')} IS NOT NULL

        UNION ALL

        SELECT
          '{_SUBTIER}:' || {q('awarding_sub_agency_code')},
          '{_SUBTIER}',
          {q('awarding_sub_agency_code')},
          {q('awarding_sub_agency_name')},
          {q(_ACTION)},
          {q(_TXN)}
        FROM {src}
        WHERE {q('awarding_sub_agency_code')} IS NOT NULL

        UNION ALL

        SELECT
          '{_TOPTIER}:' || {q('funding_agency_code')},
          '{_TOPTIER}',
          {q('funding_agency_code')},
          {q('funding_agency_name')},
          {q(_ACTION)},
          {q(_TXN)}
        FROM {src}
        WHERE {q('funding_agency_code')} IS NOT NULL

        UNION ALL

        SELECT
          '{_SUBTIER}:' || {q('funding_sub_agency_code')},
          '{_SUBTIER}',
          {q('funding_sub_agency_code')},
          {q('funding_sub_agency_name')},
          {q(_ACTION)},
          {q(_TXN)}
        FROM {src}
        WHERE {q('funding_sub_agency_code')} IS NOT NULL
    """

    return _reduce_entity(
        conn,
        table=TABLE_AGENCIES,
        observations_sql=observations,
        id_col="agency_id",
        identity_cols=("tier", "code"),
        descriptor_cols=("name",),
    )


# === Offices ===

def _materialize_offices(conn: duckdb.DuckDBPyConnection) -> int:
    """Awarding + funding offices (requires both sub-agency and office codes)."""

    q = quote_ident
    src = q(TABLE_VALID)

    def office_branch(*, sub_col: str, office_col: str, name_col: str) -> str:
        return f"""
            SELECT
              {q(sub_col)} || ':' || {q(office_col)} AS {q('office_id')},
              {q(sub_col)} AS {q('sub_agency_code')},
              {q(office_col)} AS {q('office_code')},
              {q(name_col)} AS {q('name')},
              {q(_ACTION)} AS {q(_ACTION)},
              {q(_TXN)} AS {q(_TXN)}
            FROM {src}
            WHERE {q(office_col)} IS NOT NULL
              AND {q(sub_col)} IS NOT NULL
        """

	# Union all branches
    observations = " UNION ALL ".join(
        [
            office_branch(
                sub_col="awarding_sub_agency_code",
                office_col="awarding_office_code",
                name_col="awarding_office_name",
            ),
            office_branch(
                sub_col="funding_sub_agency_code",
                office_col="funding_office_code",
                name_col="funding_office_name",
            ),
        ]
    )

    return _reduce_entity(
        conn,
        table=TABLE_OFFICES,
        observations_sql=observations,
        id_col="office_id",
        identity_cols=("sub_agency_code", "office_code"),
        descriptor_cols=("name",),
    )


# === Recipients ===

def _materialize_recipients(conn: duckdb.DuckDBPyConnection) -> int:
    """Observed recipients + parent-UEI stubs for parents never seen as recipients."""

    q = quote_ident
    src = q(TABLE_VALID)
    out = q(TABLE_RECIPIENTS)

    observed = f"""
        SELECT
          {q('recipient_uei')} AS {q('uei')},
          {q('recipient_name')} AS {q('name')},
          {q('recipient_parent_uei')} AS {q('parent_uei')},
          {q(_ACTION)} AS {q(_ACTION)},
          {q(_TXN)} AS {q(_TXN)}
        FROM {src}
        WHERE {q('recipient_uei')} IS NOT NULL
    """

    # Per-field latest non-empty, then stub parents missing from observed
    conn.execute(f"DROP TABLE IF EXISTS {out}")
    conn.execute(
        f"""
        CREATE TABLE {out} AS
        WITH observed AS (
          {observed}
        ),
        ids AS (
          SELECT DISTINCT {q('uei')} FROM observed
        ),
        best_name AS (
          SELECT {q('uei')}, {q('name')}
          FROM (
            SELECT
              {q('uei')},
              {q('name')},
              ROW_NUMBER() OVER (
                PARTITION BY {q('uei')}
                ORDER BY {q(_ACTION)} DESC, {q(_TXN)} ASC
              ) AS {q('rn')}
            FROM observed
            WHERE {q('name')} IS NOT NULL
          ) ranked
          WHERE {q('rn')} = 1
        ),
        best_parent AS (
          SELECT {q('uei')}, {q('parent_uei')}
          FROM (
            SELECT
              {q('uei')},
              {q('parent_uei')},
              ROW_NUMBER() OVER (
                PARTITION BY {q('uei')}
                ORDER BY {q(_ACTION)} DESC, {q(_TXN)} ASC
              ) AS {q('rn')}
            FROM observed
            WHERE {q('parent_uei')} IS NOT NULL
          ) ranked
          WHERE {q('rn')} = 1
        ),
        observed_reduced AS (
          SELECT
            i.{q('uei')} AS {q('uei')},
            n.{q('name')} AS {q('name')},
            p.{q('parent_uei')} AS {q('parent_uei')}
          FROM ids AS i
          LEFT JOIN best_name AS n USING ({q('uei')})
          LEFT JOIN best_parent AS p USING ({q('uei')})
        ),
        stubs AS (
          SELECT DISTINCT
            s.{q('recipient_parent_uei')} AS {q('uei')},
            CAST(NULL AS VARCHAR) AS {q('name')},
            CAST(NULL AS VARCHAR) AS {q('parent_uei')}
          FROM {src} AS s
          WHERE s.{q('recipient_parent_uei')} IS NOT NULL
            AND NOT EXISTS (
              SELECT 1
              FROM observed_reduced AS o
              WHERE o.{q('uei')} = s.{q('recipient_parent_uei')}
            )
        )
        SELECT * FROM observed_reduced
        UNION ALL
        SELECT * FROM stubs
        """
    )
    return _count(conn, TABLE_RECIPIENTS)


# === Classifications ===

def _materialize_classifications(conn: duckdb.DuckDBPyConnection) -> int:
    """NAICS + PSC codes with latest non-empty description."""

    q = quote_ident
    src = q(TABLE_VALID)
    observations = f"""
        SELECT
          '{_NAICS}:' || {q('naics_code')} AS {q('classification_id')},
          '{_NAICS}' AS {q('kind')},
          {q('naics_code')} AS {q('code')},
          {q('naics_description')} AS {q('description')},
          {q(_ACTION)} AS {q(_ACTION)},
          {q(_TXN)} AS {q(_TXN)}
        FROM {src}
        WHERE {q('naics_code')} IS NOT NULL

        UNION ALL

        SELECT
          '{_PSC}:' || {q('product_or_service_code')},
          '{_PSC}',
          {q('product_or_service_code')},
          {q('product_or_service_code_description')},
          {q(_ACTION)},
          {q(_TXN)}
        FROM {src}
        WHERE {q('product_or_service_code')} IS NOT NULL
    """

    return _reduce_entity(
        conn,
        table=TABLE_CLASSIFICATIONS,
        observations_sql=observations,
        id_col="classification_id",
        identity_cols=("kind", "code"),
        descriptor_cols=("description",),
    )


# === IDVs ===

def _materialize_idvs(conn: duckdb.DuckDBPyConnection) -> int:
    """Child-derived IDV stubs from parent PIID + award-key agency ID."""

    q = quote_ident
    src = q(TABLE_VALID)
    observations = f"""
        SELECT
          'CONT_IDV_' || {q('parent_award_id_piid')} || '_'
            || {q('parent_award_agency_id')} AS {q('idv_id')},
          {q('parent_award_id_piid')} AS {q('piid')},
          {q('parent_award_agency_id')} AS {q('award_key_agency_id')},
          {q('parent_award_type_code')} AS {q('type_code')},
          {q('parent_award_type')} AS {q('type_label')},
          '{_STUB}' AS {q('hydration_status')},
          {q(_ACTION)} AS {q(_ACTION)},
          {q(_TXN)} AS {q(_TXN)}
        FROM {src}
        WHERE {q('parent_award_id_piid')} IS NOT NULL
          AND {q('parent_award_agency_id')} IS NOT NULL
    """

    return _reduce_entity(
        conn,
        table=TABLE_IDVS,
        observations_sql=observations,
        id_col="idv_id",
        identity_cols=("piid", "award_key_agency_id", "hydration_status"),
        descriptor_cols=("type_code", "type_label"),
    )


# === Locations ===

def _materialize_locations(conn: duckdb.DuckDBPyConnection) -> int:
    """Recipient + PoP geo value-objects (skips all-empty tuples)."""

    q = quote_ident
    src = q(TABLE_VALID)
    out = q(TABLE_LOCATIONS)

    def loc_select(
        *,
        country: str,
        state: str,
        county: str,
        city: str,
        zip_col: str,
    ) -> str:
        # Codes strip-only (already trimmed in staging); city lower
        country_n = f"coalesce({q(country)}, '')"
        state_n = f"coalesce({q(state)}, '')"
        county_n = f"coalesce({q(county)}, '')"
        city_n = f"coalesce(lower({q(city)}), '')"
        zip_n = f"coalesce({q(zip_col)}, '')"
        payload = (
            f"concat_ws(chr(31), {country_n}, {state_n}, {county_n}, {city_n}, {zip_n})"
        )
        granularity = f"""
            concat_ws(
              '/',
              CASE WHEN {country_n} <> '' THEN 'country' END,
              CASE WHEN {state_n} <> '' THEN 'state' END,
              CASE WHEN {county_n} <> '' THEN 'county' END,
              CASE WHEN {city_n} <> '' THEN 'city' END,
              CASE WHEN {zip_n} <> '' THEN 'zip' END
            )
        """
        return f"""
            SELECT
              sha256({payload}) AS {q('location_id')},
              NULLIF({country_n}, '') AS {q('country_code')},
              NULLIF({state_n}, '') AS {q('state_code')},
              NULLIF({county_n}, '') AS {q('county_fips')},
              NULLIF({city_n}, '') AS {q('city_name')},
              NULLIF({zip_n}, '') AS {q('zip_code')},
              {granularity} AS {q('granularity')}
            FROM {src}
            WHERE {country_n} <> ''
              OR {state_n} <> ''
              OR {county_n} <> ''
              OR {city_n} <> ''
              OR {zip_n} <> ''
        """

    recipient = loc_select(
        country="recipient_country_code",
        state="recipient_state_code",
        county="prime_award_transaction_recipient_county_fips_code",
        city="recipient_city_name",
        zip_col="recipient_zip_4_code",
    )
    pop = loc_select(
        country="primary_place_of_performance_country_code",
        state="primary_place_of_performance_state_code",
        county="prime_award_transaction_place_of_performance_county_fips_code",
        city="primary_place_of_performance_city_name",
        zip_col="primary_place_of_performance_zip_4",
    )

    conn.execute(f"DROP TABLE IF EXISTS {out}")
    conn.execute(
        f"""
        CREATE TABLE {out} AS
        SELECT DISTINCT
          {q('location_id')},
          {q('country_code')},
          {q('state_code')},
          {q('county_fips')},
          {q('city_name')},
          {q('zip_code')},
          {q('granularity')}
        FROM (
          {recipient}
          UNION ALL
          {pop}
        ) AS locs
        """
    )
    return _count(conn, TABLE_LOCATIONS)


# === Shared Reduce ===

def _reduce_entity(
    conn: duckdb.DuckDBPyConnection,
    *,
    table: str,
    observations_sql: str,
    id_col: str,
    identity_cols: tuple[str, ...],
    descriptor_cols: tuple[str, ...],
) -> int:
    """Distinct identity + per-descriptor latest non-empty reduce."""

    q = quote_ident
    out = q(table)
    id_q = q(id_col)

    identity_agg = _SQL_LIST_SEP.join(
        f"any_value(o.{q(c)}) AS {q(c)}" for c in identity_cols
    )
    identity_from_ids = _SQL_LIST_SEP.join(
        f"ids.{q(c)} AS {q(c)}" for c in identity_cols
    )

	# Per-descriptor latest non-empty; left-join to IDs
    descriptor_joins: list[str] = []
    descriptor_selects: list[str] = []
    for i, col in enumerate(descriptor_cols):
        alias = f"d{i}"
        descriptor_joins.append(
            f"""
            LEFT JOIN (
              SELECT {id_q}, {q(col)}
              FROM (
                SELECT
                  {id_q},
                  {q(col)},
                  ROW_NUMBER() OVER (
                    PARTITION BY {id_q}
                    ORDER BY {q(_ACTION)} DESC, {q(_TXN)} ASC
                  ) AS {q('rn')}
                FROM observations
                WHERE {q(col)} IS NOT NULL
              ) ranked
              WHERE {q('rn')} = 1
            ) AS {alias}
              ON ids.{id_q} = {alias}.{id_q}
            """
        )
        descriptor_selects.append(f"{alias}.{q(col)} AS {q(col)}")

    select_parts = [f"ids.{id_q} AS {id_q}", identity_from_ids, *descriptor_selects]
    select_sql = _SQL_LIST_SEP.join(p for p in select_parts if p)

    conn.execute(f"DROP TABLE IF EXISTS {out}")
    conn.execute(
        f"""
        CREATE TABLE {out} AS
        WITH observations AS (
          {observations_sql}
        ),
        ids AS (
          SELECT
            o.{id_q} AS {id_q},
            {identity_agg}
          FROM observations AS o
          GROUP BY o.{id_q}
        )
        SELECT
          {select_sql}
        FROM ids
        {"".join(descriptor_joins)}
        """
    )
    return _count(conn, table)


# === Helpers ===

def _count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    """Count rows in `table`."""
    
    row = conn.execute(
        f"SELECT COUNT(*) FROM {quote_ident(table)}"
    ).fetchone()
    assert row is not None
    return int(row[0])

def _require_table(conn: duckdb.DuckDBPyConnection, name: str) -> None:
    """Require `table` exists, raise `ValueError` if it doesn't."""
    
    exists = conn.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = ?
        """,
        [name],
    ).fetchone()
    if exists is None or int(exists[0]) == 0:
        raise ValueError(f"{name} does not exist; load + validate first")
