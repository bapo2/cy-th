# cy_th/evidence/errors.py

"""Errors raised by the evidence tooling layer."""

# === Imports ===

from __future__ import annotations


# === Base ===

class EvidenceError(RuntimeError):
    """Base class for evidence-session failures."""


# === Session / Refs ===

class ClosedEvidenceSessionError(EvidenceError):
    """Raised when using a closed `EvidenceSession`."""

    def __init__(self, detail: str = "EvidenceSession is closed") -> None:
        self.detail = detail
        super().__init__(detail)

class InvalidSelectionRefError(EvidenceError):
    """Raised for unknown, stale, or post-close `SelectionRef` values."""

    def __init__(self, *, ref_id: str, detail: str) -> None:
        self.ref_id = ref_id
        self.detail = detail
        super().__init__(f"invalid selection ref {ref_id!r}: {detail}")

class InvalidEvidenceRequestError(EvidenceError):
    """Raised for invalid tool arguments (limits, mutually exclusive inputs, etc.)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# === Semantic ===

class SemanticUnavailableError(EvidenceError):
    """Raised when `search_contract_work` cannot open semantic resources.

    Structured evidence tools remain usable; only semantic search is blocked.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"semantic search unavailable: {detail}")
