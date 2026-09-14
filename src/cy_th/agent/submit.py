# cy_th/agent/submit.py

"""`submit_answer` terminal logic (parse args and filter citations).

Not an `EvidenceSession` capability, orchestration owns this tool. Unknown citation Award IDs are dropped (never fail the answer) and recorded for observability / anti-hallucination checks.
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from cy_th.agent.errors import InvalidModelRequestError
from cy_th.evidence.types import AwardCard


# === Constants ===

SUBMIT_ANSWER: str = "submit_answer"


# === Termination ===

class TerminationReason(StrEnum):
    """Why a procurement agent run stopped."""

    ANSWERED = "answered"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


# === Results ===

@dataclass(frozen=True, slots=True)
class CitationFilterResult:
    """Validated citation cards plus dropped unknown Award IDs."""

    citations: tuple[AwardCard, ...]
    dropped_citation_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SubmittedAnswer:
    """Accepted `submit_answer` payload after citation filtering.

    `NO_EVIDENCE`-style outcomes are still `ANSWERED` (non-empty `answer` text with empty `citations` is valid).
    """

    answer: str
    citations: tuple[AwardCard, ...]
    dropped_citation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "dropped_citation_ids": list(self.dropped_citation_ids),
        }


# === Public API ===

def filter_citations(
    citation_award_ids: Sequence[str],
    acquired: Mapping[str, AwardCard],
) -> CitationFilterResult:
    """Keep first-occurrence acquired cards; drop unknown IDs (don't fail)."""

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

def finalize_submit_answer(
    arguments: Mapping[str, Any],
    *,
    acquired: Mapping[str, AwardCard],
) -> SubmittedAnswer:
    """Parse `submit_answer` arguments and filter citations against `acquired`.

    Raises `InvalidModelRequestError` when `answer` / `citation_award_ids` are malformed.
    """

    answer = _require_answer(arguments)
    raw_ids = _require_citation_ids(arguments)
    filtered = filter_citations(raw_ids, acquired)
    return SubmittedAnswer(
        answer=answer,
        citations=filtered.citations,
        dropped_citation_ids=filtered.dropped_citation_ids,
    )


# === Arg Parsing ===

def _require_answer(args: Mapping[str, Any]) -> str:
    raw = args.get("answer")
    if raw is None:
        raise InvalidModelRequestError("submit_answer.answer is required")
    if not isinstance(raw, str):
        raise InvalidModelRequestError("submit_answer.answer must be a string")
    answer = raw.strip()
    if not answer:
        raise InvalidModelRequestError("submit_answer.answer must be non-empty")
    return answer

def _require_citation_ids(args: Mapping[str, Any]) -> tuple[str, ...]:
    if "citation_award_ids" not in args:
        raise InvalidModelRequestError("submit_answer.citation_award_ids is required")
    raw = args["citation_award_ids"]
    if raw is None:
        raise InvalidModelRequestError("submit_answer.citation_award_ids is required")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise InvalidModelRequestError(
            "submit_answer.citation_award_ids must be an array of strings"
        )
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise InvalidModelRequestError(
                "submit_answer.citation_award_ids[] must be strings"
            )
        if not item:
            raise InvalidModelRequestError(
                "submit_answer.citation_award_ids[] must be non-empty"
            )
        ids.append(item)
    return tuple(ids)
