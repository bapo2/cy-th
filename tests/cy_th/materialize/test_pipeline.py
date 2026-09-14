# tests/cy_th/materialize/test_pipeline.py

"""End-to-end materialize / publish tests (sets, `CURRENT`, integrity)."""

# === Imports ===

from __future__ import annotations
import csv
from decimal import Decimal
from pathlib import Path
import duckdb
import pytest

from cy_th.materialize.awards import materialize_awards
from cy_th.materialize.load import connect_staging, load_projected_csvs
from cy_th.materialize.paths import read_current, set_dir
from cy_th.materialize.pipeline import materialize
from cy_th.materialize.publish import (
    REJECTS_PARQUET,
    IntegrityError,
    check_integrity,
    list_set_files,
    publish_set,
)
from cy_th.materialize.references import materialize_references
from cy_th.materialize.transactions import materialize_transactions
from cy_th.materialize.validate import validate_and_dedupe
from cy_th.schema.snapshot import project_award_from_transactions
from tests.factories.projected_csv import blank_projected_row, write_projected_csv


# === Multi-Input ===

def test_multi_input_overlap_is_shard_invariant(tmp_path: Path) -> None:
    """Overlapping shard CSVs collapse to the same unique txn set as a union file."""

    rows = [
        blank_projected_row(
            contract_transaction_unique_key="T1",
            contract_award_unique_key="A1",
            total_dollars_obligated="10",
            current_total_value_of_award="10",
            potential_total_value_of_award="10",
            recipient_uei="UEI1",
            awarding_agency_code="097",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T2",
            contract_award_unique_key="A2",
            total_dollars_obligated="20",
            current_total_value_of_award="20",
            potential_total_value_of_award="20",
            recipient_uei="UEI2",
            awarding_agency_code="097",
        ),
        blank_projected_row(
            contract_transaction_unique_key="T3",
            contract_award_unique_key="A3",
            total_dollars_obligated="30",
            current_total_value_of_award="30",
            potential_total_value_of_award="30",
            recipient_uei="UEI3",
            awarding_agency_code="097",
        ),
    ]
    shard_a = write_projected_csv(tmp_path / "a.csv", rows[:2])
    shard_b = write_projected_csv(tmp_path / "b.csv", [rows[1], rows[2]])  # overlap T2
    union = write_projected_csv(tmp_path / "union.csv", rows)

    multi = materialize(
        [shard_a, shard_b],
        out=tmp_path / "multi",
        run_id="20260914T100000Z_aaaaaa",
    )
    single = materialize(
        [union],
        out=tmp_path / "single",
        run_id="20260914T100000Z_bbbbbb",
    )

    assert multi.load.rows_loaded == 4
    assert multi.validate.rows_collapsed_dupes == 1
    assert multi.validate.rows_valid == 3
    assert single.validate.rows_valid == 3
    assert multi.transactions == single.transactions == 3
    assert multi.awards == single.awards == 3
    assert multi.publish.published and single.publish.published


# === Publish / CURRENT ===

def test_clean_publish_writes_parquet_and_current(tmp_path: Path) -> None:
    csv_path = write_projected_csv(
        tmp_path / "clean.csv",
        [
            blank_projected_row(
                total_dollars_obligated="1",
                current_total_value_of_award="1",
                potential_total_value_of_award="1",
                recipient_uei="UEI1",
                awarding_agency_code="097",
            ),
        ],
    )
    result = materialize(
        [csv_path],
        out=tmp_path / "data",
        run_id="20260914T110000Z_cccccc",
        keep_staging=False,
    )
    assert result.publish.published
    assert result.publish.reject_count == 0
    assert read_current(result.data_root) == result.run_id
    assert not result.staging_path.exists()
    assert not (result.publish.set_path / REJECTS_PARQUET).exists()

    for path in list_set_files(result.publish.set_path):
        assert path.is_file()
        assert path.stat().st_size > 0

    n_row = duckdb.connect().execute(
        f"""
        SELECT COUNT(*) FROM read_parquet(
          '{(result.publish.set_path / "transactions.parquet").as_posix()}'
        )
        """
    ).fetchone()
    assert n_row is not None
    assert n_row[0] == 1

def test_immutable_set_collision(tmp_path: Path) -> None:
    csv_path = write_projected_csv(tmp_path / "one.csv", [blank_projected_row()])
    rid = "20260914T120000Z_dddddd"
    materialize([csv_path], out=tmp_path / "data", run_id=rid)
    with pytest.raises(ValueError, match="already exists"):
        materialize([csv_path], out=tmp_path / "data", run_id=rid)

def test_strict_rejects_skip_current_allow_rejects_flips(tmp_path: Path) -> None:
    good = write_projected_csv(
        tmp_path / "good.csv",
        [
            blank_projected_row(
                total_dollars_obligated="1",
                current_total_value_of_award="1",
                potential_total_value_of_award="1",
                recipient_uei="UEI1",
                awarding_agency_code="097",
            ),
        ],
    )
    prior = materialize(
        [good],
        out=tmp_path / "data",
        run_id="20260914T130000Z_eeeeee",
    )
    assert read_current(tmp_path / "data") == prior.run_id

    bad = write_projected_csv(
        tmp_path / "bad.csv",
        [
            blank_projected_row(federal_action_obligation="nope"),
            blank_projected_row(
                contract_transaction_unique_key="T2",
                contract_award_unique_key="A2",
                total_dollars_obligated="1",
                current_total_value_of_award="1",
                potential_total_value_of_award="1",
                recipient_uei="UEI2",
                awarding_agency_code="097",
            ),
        ],
    )
    strict = materialize(
        [bad],
        out=tmp_path / "data",
        run_id="20260914T130100Z_ffffff",
        allow_rejects=False,
        keep_staging=True,
    )
    assert not strict.publish.published
    assert strict.publish.reject_count >= 1
    assert read_current(tmp_path / "data") == prior.run_id
    assert (strict.publish.set_path / REJECTS_PARQUET).is_file()
    assert strict.staging_path.is_file()

    allowed = materialize(
        [bad],
        out=tmp_path / "data",
        run_id="20260914T130200Z_abcabc",
        allow_rejects=True,
    )
    assert allowed.publish.published
    assert read_current(tmp_path / "data") == allowed.run_id


# === Integrity ===

def test_integrity_failure_blocks_publish(tmp_path: Path) -> None:
    csv_path = write_projected_csv(
        tmp_path / "ok.csv",
        [
            blank_projected_row(
                total_dollars_obligated="1",
                current_total_value_of_award="1",
                potential_total_value_of_award="1",
                recipient_uei="UEI1",
                awarding_agency_code="097",
            ),
        ],
    )
    conn = connect_staging(tmp_path / "broken.duckdb")
    load_projected_csvs(conn, [csv_path])
    validate_and_dedupe(conn)
    materialize_transactions(conn)
    materialize_references(conn)
    materialize_awards(conn)

    # Remove the recipient ref while Award still points at it (breaks FK)
    conn.execute('DELETE FROM "ref_recipients"')
    integrity = check_integrity(conn)
    assert not integrity.ok
    assert any(issue.check.startswith("fk:award_record.recipient_id") for issue in integrity.issues)

    with pytest.raises(IntegrityError):
        publish_set(
            conn,
            data_root=tmp_path / "data",
            run_id="20260914T140000Z_ffffff",
        )
    assert not set_dir(tmp_path / "data", "20260914T140000Z_ffffff").exists()
    assert read_current(tmp_path / "data") is None


# === Real Extract ===

def test_real_extract_materialize_and_oracle_sample(
    tmp_path: Path,
    prime_txn_csv_path: Path,
) -> None:
    """Publish succeeds on full cached day + sample awards match snapshot oracle."""

    result = materialize(
        [prime_txn_csv_path],
        out=tmp_path / "real",
        run_id="20260914T150000Z_aa11aa",
    )
    assert result.publish.published
    assert result.publish.reject_count == 0
    assert result.transactions == result.validate.rows_valid
    assert result.awards > 0
    assert read_current(result.data_root) == result.run_id

    # Re-open staging is gone; use Parquet awards + rebuild oracle w/ source CSV
    awards = duckdb.connect().execute(
        f"""
        SELECT award_id, projection_transaction_id,
               snapshot_status, snapshot_source,
               snapshot_transaction_id, observed_total_obligation,
               observed_current_value, observed_potential_value
        FROM read_parquet('{(result.publish.set_path / "awards.parquet").as_posix()}')
        USING SAMPLE 40
        """
    ).fetchall()
    assert awards

    # Index source rows by award for oracle inputs
    by_award: dict[str, list[dict[str, object]]] = {}
    with prime_txn_csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            award_id = (row.get("contract_award_unique_key") or "").strip()
            if not award_id:
                continue
            by_award.setdefault(award_id, []).append(
                {
                    "transaction_id": row["contract_transaction_unique_key"],
                    "action_date": row["action_date"],
                    "transaction_number": row.get("transaction_number") or None,
                    "total_dollars_obligated": row.get("total_dollars_obligated") or None,
                    "current_total_value_of_award": row.get("current_total_value_of_award")
                    or None,
                    "potential_total_value_of_award": row.get(
                        "potential_total_value_of_award"
                    )
                    or None,
                }
            )

    for got in awards:
        award_id = got[0]
        oracle = project_award_from_transactions(by_award[award_id])
        assert got[1] == oracle.projection_transaction_id
        assert got[2] == oracle.snapshot_status.value
        assert got[3] == oracle.snapshot_source.value
        assert got[4] == oracle.snapshot_transaction_id
        assert _dec_or_none(got[5]) == oracle.observed_total_obligation
        assert _dec_or_none(got[6]) == oracle.observed_current_value
        assert _dec_or_none(got[7]) == oracle.observed_potential_value

def _dec_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
