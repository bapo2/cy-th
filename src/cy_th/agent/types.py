# cy_th/agent/types.py

"""Typed models for the procurement agent (answers, budgets, trace)."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from cy_th.evidence.types import AwardCard


# === Model / Budgets ===

DEFAULT_MODEL: str = "gpt-5.6-sol"

DEFAULT_MAX_ROUNDS: int = 6
HARD_MAX_ROUNDS: int = 10

DEFAULT_MAX_TOOL_CALLS: int = 12
HARD_MAX_TOOL_CALLS: int = 24

def clamp_budget(value: int, *, hard_max: int, name: str) -> int:
    """Reject non-positive budgets; clamp to `hard_max`."""

    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return min(value, hard_max)


# === Termination ===

class TerminationReason(StrEnum):
    """Why `ProcurementAgent.answer` stopped."""

    ANSWERED = "answered"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


# === Trace / Answer ===

@dataclass(frozen=True, slots=True)
class ToolTraceEntry:
    """One procurement or submit_answer dispatch recorded on `AgentAnswer`."""

    round: int
    name: str
    arguments: Mapping[str, Any]
    ok: bool
    observation: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "name": self.name,
            "arguments": dict(self.arguments),
            "ok": self.ok,
            "observation": dict(self.observation),
        }

@dataclass(frozen=True, slots=True)
class AgentAnswer:
    """Structured result of one bounded agent run."""

    text: str
    citations: tuple[AwardCard, ...]
    dropped_citation_ids: tuple[str, ...]
    termination_reason: TerminationReason
    rounds: int
    tool_calls: int
    tool_trace: tuple[ToolTraceEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citations": [c.to_dict() for c in self.citations],
            "dropped_citation_ids": list(self.dropped_citation_ids),
            "termination_reason": self.termination_reason.value,
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tool_trace": [e.to_dict() for e in self.tool_trace],
        }


# === Citations ===

@dataclass(frozen=True, slots=True)
class CitationFilterResult:
    """Validated citation cards plus dropped unknown Award IDs."""

    citations: tuple[AwardCard, ...]
    dropped_citation_ids: tuple[str, ...]

def filter_citations(
    citation_award_ids: Sequence[str],
    acquired: Mapping[str, AwardCard],
) -> CitationFilterResult:
    """Keep first-occurrence acquired cards; drop unknown IDs (don't fail due to this)."""

    citations: list[AwardCard] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for award_id in citation_award_ids:
        if award_id in seen:
            continue
        seen.add(award_id)
        card = acquired.get(award_id)
        if card is None:
            dropped.append(award_id)
        else:
            citations.append(card)
    return CitationFilterResult(
        citations=tuple(citations),
        dropped_citation_ids=tuple(dropped),
    )
