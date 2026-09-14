# cy_th/semantic/documents.py

"""Deterministic Award semantic document projection and assembly."""

# === Imports ===

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence
import duckdb

from cy_th.materialize.awards import TABLE_AWARDS
from cy_th.materialize.references import (
    TABLE_AGENCIES,
    TABLE_CLASSIFICATIONS,
    TABLE_RECIPIENTS,
)
from cy_th.materialize.transactions import TABLE_TRANSACTIONS
from cy_th.schema.db_types import quote_ident
from cy_th.semantic.paths import TEXT_BUDGET, document_id_for_award
from cy_th.semantic.types import SemanticDocument


# === Source Row ===

@dataclass(frozen=True, slots=True)
class AwardSemanticSource:
    """Raw fields used to assemble one Award semantic document.

    `transaction_descriptions` must already be newest-first, readable-normalized, and deduped.
    """

    award_id: str
    base_description: str | None
    psc_code: str | None
    psc_description: str | None
    naics_code: str | None
    naics_description: str | None
    recipient_name: str | None
    awarding_agency_name: str | None
    awarding_sub_agency_name: str | None
    transaction_descriptions: tuple[str, ...]


# === Text Normalization ===

def collapse_whitespace(value: str) -> str:
    """Split on Unicode whitespace and re-join with a single ASCII space."""

    return " ".join(value.split())

def normalize_readable(value: str | None) -> str | None:
    """Strip + collapse whitespace; preserve case. Empty → `None`."""

    if value is None:
        return None
    text = collapse_whitespace(value.strip())
    return text or None

def dedupe_key(value: str) -> str:
    """Dedupe key for transaction descriptions (`casefold` of readable form)."""

    readable = normalize_readable(value)
    assert readable is not None
    return readable.casefold()


# === Assembly ===

def is_work_bearing(source: AwardSemanticSource) -> bool:
    """Return whether `source` has any work-bearing text (labels alone don't count)."""

    if source.base_description is not None:
        return True
    if source.psc_description is not None:
        return True
    if source.naics_description is not None:
        return True
    return len(source.transaction_descriptions) > 0

def assemble_document(
    source: AwardSemanticSource,
    *,
    text_budget: int = TEXT_BUDGET,
) -> SemanticDocument | None:
    """Assemble one semantic document (or `None` when not indexable)."""

    if text_budget < 0:
        raise ValueError("text_budget must be >= 0")
    if not is_work_bearing(source):
        return None

    text = ""

    if source.base_description is not None:
        text, cont = _append_segment(
            text, f"Award description: {source.base_description}", text_budget
        )
        if not cont:
            return _document(source.award_id, text)

    if source.psc_code is not None and source.psc_description is not None:
        text, cont = _append_segment(
            text,
            f"PSC: {source.psc_code}; {source.psc_description}",
            text_budget,
        )
        if not cont:
            return _document(source.award_id, text)

    if source.naics_code is not None and source.naics_description is not None:
        text, cont = _append_segment(
            text,
            f"NAICS: {source.naics_code}; {source.naics_description}",
            text_budget,
        )
        if not cont:
            return _document(source.award_id, text)

    text, cont = _append_transaction_section(
        text, source.transaction_descriptions, text_budget
    )
    if not cont:
        return _document(source.award_id, text)

    if source.recipient_name is not None:
        text, cont = _append_segment(
            text, f"Recipient: {source.recipient_name}", text_budget
        )
        if not cont:
            return _document(source.award_id, text)

    if source.awarding_agency_name is not None:
        text, cont = _append_segment(
            text, f"Awarding agency: {source.awarding_agency_name}", text_budget
        )
        if not cont:
            return _document(source.award_id, text)

    if source.awarding_sub_agency_name is not None:
        text, _ = _append_segment(
            text,
            f"Awarding sub-agency: {source.awarding_sub_agency_name}",
            text_budget,
        )

    return _document(source.award_id, text)

def build_award_source(
    *,
    award_id: str,
    base_description: str | None,
    psc_code: str | None,
    psc_description: str | None,
    naics_code: str | None,
    naics_description: str | None,
    recipient_name: str | None,
    awarding_agency_name: str | None,
    awarding_sub_agency_name: str | None,
    transaction_rows: Sequence[tuple[date | None, str, str | None]],
) -> AwardSemanticSource:
    """Normalize fields and dedupe transaction descriptions (newest-first).

    `transaction_rows` entries are `(action_date, transaction_id, description)` in any order (they're sorted here).
    """

    # `action_date DESC` (nulls last), then `transaction_id ASC`
    ordered = sorted(
        transaction_rows,
        key=lambda row: (
            row[0] is None,
            -(row[0].toordinal()) if row[0] is not None else 0,
            row[1],
        ),
    )

    seen: set[str] = set()
    txn_texts: list[str] = []
    for _action_date, _txn_id, raw in ordered:
        readable = normalize_readable(raw)
        if readable is None:
            continue
        key = readable.casefold()
        if key in seen:
            continue
        seen.add(key)
        txn_texts.append(readable)

    psc_desc = normalize_readable(psc_description)
    naics_desc = normalize_readable(naics_description)
    return AwardSemanticSource(
        award_id=award_id,
        base_description=normalize_readable(base_description),
        psc_code=normalize_readable(psc_code) if psc_desc is not None else None,
        psc_description=psc_desc,
        naics_code=normalize_readable(naics_code) if naics_desc is not None else None,
        naics_description=naics_desc,
        recipient_name=normalize_readable(recipient_name),
        awarding_agency_name=normalize_readable(awarding_agency_name),
        awarding_sub_agency_name=normalize_readable(awarding_sub_agency_name),
        transaction_descriptions=tuple(txn_texts),
    )


# === Projection ===

def project_semantic_documents(
    conn: duckdb.DuckDBPyConnection,
    *,
    text_budget: int = TEXT_BUDGET,
) -> list[SemanticDocument]:
    """Project indexable Award semantic documents from registered canonical views.

    Result is sorted by `award_id ASC`. Awards without work-bearing text are omitted.
    """

    txns_by_award = _load_transaction_rows(conn)
    docs: list[SemanticDocument] = []

    for row in _load_award_rows(conn):
        (
            award_id,
            base_description,
            psc_code,
            psc_description,
            naics_code,
            naics_description,
            recipient_name,
            awarding_agency_name,
            awarding_sub_agency_name,
        ) = row
        source = build_award_source(
            award_id=award_id,
            base_description=base_description,
            psc_code=psc_code,
            psc_description=psc_description,
            naics_code=naics_code,
            naics_description=naics_description,
            recipient_name=recipient_name,
            awarding_agency_name=awarding_agency_name,
            awarding_sub_agency_name=awarding_sub_agency_name,
            transaction_rows=txns_by_award.get(award_id, ()),
        )
        doc = assemble_document(source, text_budget=text_budget)
        if doc is not None:
            docs.append(doc)

    docs.sort(key=lambda d: d.award_id)
    return docs


# === Helpers ===

def _document(award_id: str, text: str) -> SemanticDocument:
    return SemanticDocument(
        award_id=award_id,
        document_id=document_id_for_award(award_id),
        text=text,
    )

def _append_segment(current: str, segment: str, budget: int) -> tuple[str, bool]:
    """Append `segment` under `budget`.

    #### Returns:
        `(new_text, continue)` where `continue` is `False` when the budget is exhausted (after optional truncation)
    """

    if not segment:
        return current, True

    sep = "\n" if current else ""
    room = budget - len(current) - len(sep)
    if room <= 0:
        return current, False
    if len(segment) <= room:
        return current + sep + segment, True
    return current + sep + segment[:room], False

def _append_transaction_section(
    current: str,
    descriptions: Sequence[str],
    budget: int,
) -> tuple[str, bool]:
    """Append the transaction block only when at least one bullet fits."""

    if not descriptions:
        return current, True

    header = "Transaction work descriptions:"
    tentative, cont = _append_segment(current, header, budget)
    if tentative == current:
        return current, False

    wrote_line = False
    text = tentative
    for desc in descriptions:
        line = f"- {desc}"
        before = text
        text, cont = _append_segment(text, line, budget)
        if text != before:
            wrote_line = True
        if not cont:
            break

    if not wrote_line:
        return current, True  # Drop header-only block (budget may still allow labels)
    return text, cont

def _load_award_rows(
    conn: duckdb.DuckDBPyConnection,
) -> list[
    tuple[
        str,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
    ]
]:
    a = quote_ident(TABLE_AWARDS)
    r = quote_ident(TABLE_RECIPIENTS)
    ag = quote_ident(TABLE_AGENCIES)
    cl = quote_ident(TABLE_CLASSIFICATIONS)
    rows = conn.execute(
        f"""
        SELECT
          a.{quote_ident('award_id')},
          a.{quote_ident('base_description')},
          psc.{quote_ident('code')},
          psc.{quote_ident('description')},
          naics.{quote_ident('code')},
          naics.{quote_ident('description')},
          rec.{quote_ident('name')},
          aw.{quote_ident('name')},
          aws.{quote_ident('name')}
        FROM {a} AS a
        LEFT JOIN {r} AS rec
          ON rec.{quote_ident('uei')} = a.{quote_ident('recipient_id')}
        LEFT JOIN {ag} AS aw
          ON aw.{quote_ident('agency_id')} = a.{quote_ident('awarding_agency_id')}
        LEFT JOIN {ag} AS aws
          ON aws.{quote_ident('agency_id')} = a.{quote_ident('awarding_sub_agency_id')}
        LEFT JOIN {cl} AS psc
          ON psc.{quote_ident('classification_id')} = a.{quote_ident('psc_id')}
        LEFT JOIN {cl} AS naics
          ON naics.{quote_ident('classification_id')} = a.{quote_ident('naics_id')}
        ORDER BY a.{quote_ident('award_id')} ASC
        """
    ).fetchall()
    return [
        (
            str(row[0]),
            _as_optional_str(row[1]),
            _as_optional_str(row[2]),
            _as_optional_str(row[3]),
            _as_optional_str(row[4]),
            _as_optional_str(row[5]),
            _as_optional_str(row[6]),
            _as_optional_str(row[7]),
            _as_optional_str(row[8]),
        )
        for row in rows
    ]

def _load_transaction_rows(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, list[tuple[date | None, str, str | None]]]:
    t = quote_ident(TABLE_TRANSACTIONS)
    rows = conn.execute(
        f"""
        SELECT
          {quote_ident('award_id')},
          {quote_ident('action_date')},
          {quote_ident('transaction_id')},
          {quote_ident('transaction_description')}
        FROM {t}
        """
    ).fetchall()
    out: dict[str, list[tuple[date | None, str, str | None]]] = defaultdict(list)
    for award_id, action_date, transaction_id, description in rows:
        out[str(award_id)].append(
            (
                action_date if isinstance(action_date, date) else None,
                str(transaction_id),
                _as_optional_str(description),
            )
        )
    return out

def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
