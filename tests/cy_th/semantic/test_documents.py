# tests/cy_th/semantic/test_documents.py

"""Unit tests for semantic document normalization and assembly."""

# === Imports ===

from __future__ import annotations
from datetime import date
import pytest

from cy_th.semantic.documents import (
    assemble_document,
    build_award_source,
    collapse_whitespace,
    dedupe_key,
    is_work_bearing,
    normalize_readable,
)
from cy_th.semantic.paths import document_id_for_award


# === Normalization ===

def test_collapse_whitespace_and_readable() -> None:
    assert collapse_whitespace("  a\t\nb  ") == "a b"
    assert normalize_readable("  Hello\nWorld  ") == "Hello World"
    assert normalize_readable("   ") is None
    assert normalize_readable(None) is None
    assert dedupe_key("  Radar Detection  ") == "radar detection"

def test_document_id_namespace() -> None:
    assert document_id_for_award("A1") == "award:A1"


# === Work-Bearing ===

def test_labels_alone_are_not_work_bearing() -> None:
    source = build_award_source(
        award_id="A_EMPTY",
        base_description=None,
        psc_code="D302",
        psc_description=None,
        naics_code="541511",
        naics_description=None,
        recipient_name="Vendor",
        awarding_agency_name="DoD",
        awarding_sub_agency_name="Navy",
    )
    assert not is_work_bearing(source)
    assert assemble_document(source) is None

def test_psc_code_without_description_is_omitted() -> None:
    source = build_award_source(
        award_id="A1",
        base_description="Work text",
        psc_code="D302",
        psc_description=None,
        naics_code=None,
        naics_description=None,
        recipient_name=None,
        awarding_agency_name=None,
        awarding_sub_agency_name=None,
    )
    doc = assemble_document(source)
    assert doc is not None
    assert "PSC:" not in doc.text
    assert "Award description: Work text" in doc.text


# === Assembly Order / Budget ===

def test_assembly_order_and_sections() -> None:
    source = build_award_source(
        award_id="A1",
        base_description="Base work",
        psc_code="R425",
        psc_description="Engineering",
        naics_code="541330",
        naics_description="Engineering Services",
        recipient_name="Acme",
        awarding_agency_name="DoD",
        awarding_sub_agency_name="Navy",
        transaction_descriptions=["Txn newest", "Txn older"],
    )
    doc = assemble_document(source)
    assert doc is not None
    assert doc.document_id == "award:A1"
    text = doc.text
    assert text.index("Award description:") < text.index("PSC:")
    assert text.index("PSC:") < text.index("NAICS:")
    assert text.index("NAICS:") < text.index("Transaction work descriptions:")
    assert text.index("Transaction work descriptions:") < text.index("Recipient:")
    assert text.index("Recipient:") < text.index("Awarding agency:")
    assert text.index("Awarding agency:") < text.index("Awarding sub-agency:")
    assert "- Txn newest" in text
    assert "- Txn older" in text

def test_budget_truncates_at_codepoint_boundary() -> None:
    source = build_award_source(
        award_id="A1",
        base_description="ABCDEFGHIJ",
        psc_code=None,
        psc_description=None,
        naics_code=None,
        naics_description=None,
        recipient_name=None,
        awarding_agency_name=None,
        awarding_sub_agency_name=None,
    )
    doc = assemble_document(source, text_budget=25)
    assert doc is not None
    assert len(doc.text) <= 25
    assert doc.text.startswith("Award description:")

def test_transaction_dedupe_keeps_newest_readable_form() -> None:
    source = build_award_source(
        award_id="A_TXN",
        base_description=None,
        psc_code=None,
        psc_description=None,
        naics_code=None,
        naics_description=None,
        recipient_name=None,
        awarding_agency_name=None,
        awarding_sub_agency_name=None,
        transaction_rows=(
            (date(2025, 1, 1), "T_OLD", "Same Work"),
            (date(2025, 6, 1), "T_NEW", "same work"),
            (date(2025, 6, 15), "T_U", "Unique line"),
        ),
    )
    assert source.transaction_descriptions == ("Unique line", "same work")
    doc = assemble_document(source)
    assert doc is not None
    assert "same work" in doc.text
    assert "Unique line" in doc.text
    # Newest dupe spelling wins (June row); older January form is dropped
    assert "Same Work" not in doc.text

def test_negative_budget_rejected() -> None:
    source = build_award_source(
        award_id="A1",
        base_description="x",
        psc_code=None,
        psc_description=None,
        naics_code=None,
        naics_description=None,
        recipient_name=None,
        awarding_agency_name=None,
        awarding_sub_agency_name=None,
    )
    with pytest.raises(ValueError, match="text_budget"):
        assemble_document(source, text_budget=-1)
