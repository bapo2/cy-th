# cy_th/enrichment/errors.py

"""Errors raised by lazy enrichment."""

# === Imports ===

from __future__ import annotations


# === Base ===

class EnrichmentError(RuntimeError):
    """Base class for enrichment failures."""


# === Local ===

class UnknownLocalIdentityError(EnrichmentError):
    """Raised when the Award / IDV is not in the pinned local dataset."""

    def __init__(self, *, kind: str, identity: str) -> None:
        self.kind = kind
        self.identity = identity
        super().__init__(f"local {kind} not found: {identity}")


# === Transport ===

class UsaSpendingDetailError(EnrichmentError):
    """Raised when a USASpending award-detail request fails."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
