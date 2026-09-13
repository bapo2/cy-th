# cy_th/schema/enums.py

"""Enumerations for canonical record contracts."""

# === Imports ===

from enum import StrEnum


# === Snapshot ===

class SnapshotStatus(StrEnum):
    """Quality of locally observed Award money state."""

    DEFENSIBLE = "defensible"
    """Eligible latest-day candidates agree on all three non-null money fields."""

    REQUIRES_ENRICHMENT = "requires_enrichment"
    """No eligible candidates, conflict, or partial nulls among money fields."""

    NOT_OBSERVED = "not_observed"
    """Eligible candidates exist, but all three money fields are null."""

class SnapshotSource(StrEnum):
    """Provenance of Award money-snapshot values (separate from quality)."""

    TRANSACTION = "transaction"
    """Derived from local `TransactionFact` rows."""

    AWARD_DETAIL = "award_detail"
    """Supplied by award-detail enrichment."""

    NONE = "none"
    """No snapshot source yet (typical for `requires_enrichment` at first materialize)."""


# === Agency ===

class AgencyTier(StrEnum):
    """USASpending agency tier for `AgencyRef` identity `(tier, code)`."""

    TOPTIER = "toptier"
    SUBTIER = "subtier"


# === Classification ===

class ClassificationKind(StrEnum):
    """Discriminator for `ClassificationRef`."""

    NAICS = "NAICS"
    PSC = "PSC"


# === IDV ===

class HydrationStatus(StrEnum):
    """Whether an `IDVRef` has been enriched beyond child-derived stub fields."""

    STUB = "stub"
    """Constructed from child transaction parent fields only."""

    HYDRATED = "hydrated"
    """Populated from authoritative IDV / award-detail enrichment."""
