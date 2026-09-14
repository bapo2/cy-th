# tests/cy_th/enrichment/test_service.py

"""Offline enrichment overlays (`FakeDetailClient`)."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal
import pytest

from cy_th.enrichment.errors import UnknownLocalIdentityError
from cy_th.enrichment.fake import FakeDetailClient
from cy_th.enrichment.service import (
    enrich_award,
    enrich_idv,
    evict_award_cache,
    evict_idv_cache,
)
from cy_th.query.dataset import ProcurementDataset
from cy_th.schema.enums import HydrationStatus, SnapshotSource, SnapshotStatus
from tests.cy_th.enrichment.conftest import DEF_AWARD, IDV_ID, REQ_AWARD


# === Helpers ===

def _award_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "date_signed": "2020-06-01",
        "total_obligation": 999.0,
        "base_exercised_options": 888.0,
        "base_and_all_options": 777.0,
        "type": "A",
        "type_description": "Definitive Contract",
    }
    base.update(overrides)
    return base

def _idv_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "date_signed": "2022-10-28",
        "type": "IDV_B_B",
        "type_description": "IDC",
    }
    base.update(overrides)
    return base


# === Award ===

def test_enrich_award_fills_date_signed_without_money_when_defensible(
    enrich_dataset: ProcurementDataset,
) -> None:
    client = FakeDetailClient(payloads={DEF_AWARD: _award_payload()})
    result = enrich_award(enrich_dataset, DEF_AWARD, client=client)
    assert result.date_signed == date(2020, 6, 1)
    assert result.money_applied is False
    assert result.snapshot_status is SnapshotStatus.DEFENSIBLE
    assert result.snapshot_source is SnapshotSource.TRANSACTION
    assert result.observed_total_obligation == Decimal("100")
    assert result.cache_path.is_file()
    assert client.fetch_calls == [DEF_AWARD]

def test_enrich_award_applies_money_only_for_requires_enrichment(
    enrich_dataset: ProcurementDataset,
) -> None:
    assert enrich_dataset.conn.execute(
        "SELECT snapshot_status FROM award_record WHERE award_id = ?",
        [REQ_AWARD],
    ).fetchone()[0] == SnapshotStatus.REQUIRES_ENRICHMENT.value

    client = FakeDetailClient(payloads={REQ_AWARD: _award_payload()})
    result = enrich_award(enrich_dataset, REQ_AWARD, client=client)
    assert result.money_applied is True
    assert result.snapshot_status is SnapshotStatus.DEFENSIBLE
    assert result.snapshot_source is SnapshotSource.AWARD_DETAIL
    assert result.observed_total_obligation == Decimal("999.0")
    assert result.observed_current_value == Decimal("888.0")
    assert result.observed_potential_value == Decimal("777.0")
    # Parquet unchanged
    row = enrich_dataset.conn.execute(
        "SELECT snapshot_status, date_signed FROM award_record WHERE award_id = ?",
        [REQ_AWARD],
    ).fetchone()
    assert row[0] == SnapshotStatus.REQUIRES_ENRICHMENT.value
    assert row[1] is None

def test_enrich_award_cache_hit_skips_network(
    enrich_dataset: ProcurementDataset,
) -> None:
    client = FakeDetailClient(payloads={DEF_AWARD: _award_payload()})
    first = enrich_award(enrich_dataset, DEF_AWARD, client=client)
    second = enrich_award(enrich_dataset, DEF_AWARD, client=client)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert client.fetch_calls == [DEF_AWARD]

def test_evict_award_forces_refetch(enrich_dataset: ProcurementDataset) -> None:
    client = FakeDetailClient(payloads={DEF_AWARD: _award_payload()})
    enrich_award(enrich_dataset, DEF_AWARD, client=client)
    assert evict_award_cache(enrich_dataset.data_root, DEF_AWARD) is True
    again = enrich_award(enrich_dataset, DEF_AWARD, client=client)
    assert again.cache_hit is False
    assert client.fetch_calls == [DEF_AWARD, DEF_AWARD]

def test_unknown_award_rejected(enrich_dataset: ProcurementDataset) -> None:
    with pytest.raises(UnknownLocalIdentityError, match="award"):
        enrich_award(enrich_dataset, "missing", client=FakeDetailClient())


# === IDV ===

def test_enrich_idv_hydrates_overlay_without_mutating_parquet(
    enrich_dataset: ProcurementDataset,
) -> None:
    local = enrich_dataset.conn.execute(
        "SELECT hydration_status FROM ref_idvs WHERE idv_id = ?",
        [IDV_ID],
    ).fetchone()
    assert local is not None
    assert local[0] == HydrationStatus.STUB.value

    client = FakeDetailClient(payloads={IDV_ID: _idv_payload()})
    result = enrich_idv(enrich_dataset, IDV_ID, client=client)
    assert result.hydration_status is HydrationStatus.HYDRATED
    assert result.type_code == "IDV_B_B"
    assert result.type_label == "IDC"
    assert result.cache_path.is_file()

    after = enrich_dataset.conn.execute(
        "SELECT hydration_status, type_code FROM ref_idvs WHERE idv_id = ?",
        [IDV_ID],
    ).fetchone()
    assert after[0] == HydrationStatus.STUB.value

def test_evict_idv_cache(enrich_dataset: ProcurementDataset) -> None:
    client = FakeDetailClient(payloads={IDV_ID: _idv_payload()})
    first = enrich_idv(enrich_dataset, IDV_ID, client=client)
    assert first.cache_hit is False
    assert evict_idv_cache(enrich_dataset.data_root, IDV_ID) is True
    again = enrich_idv(enrich_dataset, IDV_ID, client=client)
    assert again.cache_hit is False
    assert client.fetch_calls == [IDV_ID, IDV_ID]
