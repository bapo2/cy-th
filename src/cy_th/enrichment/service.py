# cy_th/enrichment/service.py

"""Enrich Awards / IDVs via cache + USASpending award detail (overlay only)."""

# === Imports ===

from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from cy_th.enrichment.cache import (
    award_detail_endpoint,
    evict_cache,
    new_award_cache_doc,
    new_idv_cache_doc,
    read_cache_doc,
    write_cache_doc,
)
from cy_th.enrichment.client import UsaSpendingDetailClient
from cy_th.enrichment.errors import UnknownLocalIdentityError
from cy_th.enrichment.paths import award_cache_path, idv_cache_path
from cy_th.enrichment.reconcile import (
    overlay_award_money,
    parse_date_signed,
    select_award_fields,
    select_idv_fields,
)
from cy_th.enrichment.types import (
    AwardEnrichment,
    AwardSelected,
    DetailClient,
    IdvEnrichment,
    IdvSelected,
    LocalAwardRow,
    LocalIdvRow,
)
from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import TABLE_IDVS
from cy_th.query.dataset import ProcurementDataset
from cy_th.schema.db_types import quote_ident
from cy_th.schema.enums import HydrationStatus, SnapshotSource, SnapshotStatus


# === Public API ===

def enrich_award(
    dataset: ProcurementDataset,
    award_id: str,
    *,
    client: DetailClient | None = None,
    force_refresh: bool = False,
) -> AwardEnrichment:
    """Fetch/cache award detail and return an overlay (Parquet unchanged).

    Money from detail is applied only when local `snapshot_status` is `requires_enrichment`.
    """

    local = _load_local_award(dataset, award_id)
    path = award_cache_path(dataset.data_root, award_id)
    resolved = client if client is not None else UsaSpendingDetailClient()

    doc, cache_hit = _load_or_fetch_award(
        path,
        award_id=award_id,
        client=resolved,
        force_refresh=force_refresh,
    )
    selected = AwardSelected.from_dict(doc.get("selected") or {})
    date_signed = parse_date_signed(selected)
    if date_signed is None:
        date_signed = local.date_signed

    money_applied, total, current, potential, status, source = overlay_award_money(
        local, selected
    )

    return AwardEnrichment(
        award_id=award_id,
        cache_path=path,
        cache_hit=cache_hit,
        endpoint=str(doc.get("endpoint") or award_detail_endpoint(award_id)),
        retrieved_at=str(doc.get("retrieved_at") or ""),
        date_signed=date_signed,
        money_applied=money_applied,
        observed_total_obligation=total,
        observed_current_value=current,
        observed_potential_value=potential,
        snapshot_status=status,
        snapshot_source=source,
        local=local,
    )

def enrich_idv(
    dataset: ProcurementDataset,
    idv_id: str,
    *,
    client: DetailClient | None = None,
    force_refresh: bool = False,
) -> IdvEnrichment:
    """Fetch/cache IDV detail and return a hydrated overlay (Parquet stub unchanged)."""

    local = _load_local_idv(dataset, idv_id)
    path = idv_cache_path(dataset.data_root, idv_id)
    resolved = client if client is not None else UsaSpendingDetailClient()

    doc, cache_hit = _load_or_fetch_idv(
        path,
        idv_id=idv_id,
        client=resolved,
        force_refresh=force_refresh,
    )
    selected = IdvSelected.from_dict(doc.get("selected") or {})
    type_code = selected.type_code if selected.type_code else local.type_code
    type_label = selected.type_label if selected.type_label else local.type_label

    return IdvEnrichment(
        idv_id=idv_id,
        cache_path=path,
        cache_hit=cache_hit,
        endpoint=str(doc.get("endpoint") or award_detail_endpoint(idv_id)),
        retrieved_at=str(doc.get("retrieved_at") or ""),
        type_code=type_code,
        type_label=type_label,
        hydration_status=HydrationStatus.HYDRATED,
        local=local,
    )

def evict_award_cache(data_root: Path | str | None, award_id: str) -> bool:
    """Remove a cached award-detail document if present."""

    return evict_cache(award_cache_path(data_root, award_id))

def evict_idv_cache(data_root: Path | str | None, idv_id: str) -> bool:
    """Remove a cached IDV-detail document if present."""

    return evict_cache(idv_cache_path(data_root, idv_id))


# === Cache / Fetch ===

def _load_or_fetch_award(
    path: Path,
    *,
    award_id: str,
    client: DetailClient,
    force_refresh: bool,
) -> tuple[dict[str, Any], bool]:
    if not force_refresh:
        existing = read_cache_doc(path)
        if existing is not None and existing.get("source_id") == award_id:
            return existing, True

    payload = client.fetch_award_detail(award_id)
    selected = select_award_fields(payload)
    doc = new_award_cache_doc(award_id=award_id, payload=payload, selected=selected)
    write_cache_doc(path, doc)
    return doc, False

def _load_or_fetch_idv(
    path: Path,
    *,
    idv_id: str,
    client: DetailClient,
    force_refresh: bool,
) -> tuple[dict[str, Any], bool]:
    if not force_refresh:
        existing = read_cache_doc(path)
        if existing is not None and existing.get("source_id") == idv_id:
            return existing, True

    payload = client.fetch_award_detail(idv_id)
    selected = select_idv_fields(payload)
    doc = new_idv_cache_doc(idv_id=idv_id, payload=payload, selected=selected)
    write_cache_doc(path, doc)
    return doc, False


# === Local Loads ===

def _load_local_award(dataset: ProcurementDataset, award_id: str) -> LocalAwardRow:
    q = quote_ident
    table = q(TABLE_AWARDS)
    row = dataset.conn.execute(
        f"""
        SELECT
          {q('award_id')},
          {q('snapshot_status')},
          {q('snapshot_source')},
          {q('observed_total_obligation')},
          {q('observed_current_value')},
          {q('observed_potential_value')},
          {q('date_signed')},
          {q('parent_idv_id')}
        FROM {table}
        WHERE {q('award_id')} = ?
        """,
        [award_id],
    ).fetchone()
    if row is None:
        raise UnknownLocalIdentityError(kind="award", identity=award_id)
    return LocalAwardRow(
        award_id=str(row[0]),
        snapshot_status=SnapshotStatus(str(row[1])),
        snapshot_source=SnapshotSource(str(row[2])),
        observed_total_obligation=_as_decimal(row[3]),
        observed_current_value=_as_decimal(row[4]),
        observed_potential_value=_as_decimal(row[5]),
        date_signed=_as_date(row[6]),
        parent_idv_id=_as_optional_str(row[7]),
    )

def _load_local_idv(dataset: ProcurementDataset, idv_id: str) -> LocalIdvRow:
    q = quote_ident
    table = q(TABLE_IDVS)
    row = dataset.conn.execute(
        f"""
        SELECT
          {q('idv_id')},
          {q('piid')},
          {q('award_key_agency_id')},
          {q('type_code')},
          {q('type_label')},
          {q('hydration_status')}
        FROM {table}
        WHERE {q('idv_id')} = ?
        """,
        [idv_id],
    ).fetchone()
    if row is None:
        raise UnknownLocalIdentityError(kind="idv", identity=idv_id)
    return LocalIdvRow(
        idv_id=str(row[0]),
        piid=str(row[1]),
        award_key_agency_id=str(row[2]),
        type_code=_as_optional_str(row[3]),
        type_label=_as_optional_str(row[4]),
        hydration_status=HydrationStatus(str(row[5])),
    )


# === Coercion ===

def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None

def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])

def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
