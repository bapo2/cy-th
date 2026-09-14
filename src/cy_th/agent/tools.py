# cy_th/agent/tools.py

"""Available tool definitions for the procurement agent (`ToolSpec` catalog).

`EVIDENCE_TOOLS` is the procurement surface; `AGENT_TOOLS` adds terminal `submit_answer`. Execution lives in `cy_th.agent.dispatch`.
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from cy_th.agent.types import ToolSpec


# === Catalog ===

@dataclass(frozen=True, slots=True)
class ToolDefinitions:
    """Immutable set of available tools, keyed by name."""

    specs: tuple[ToolSpec, ...]

    def __post_init__(self) -> None:
        names = [spec.name for spec in self.specs]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names in ToolDefinitions: {names}")

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self.specs)

    def __len__(self) -> int:
        return len(self.specs)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def get(self, name: str) -> ToolSpec | None:
        """Return the spec for `name`, or `None` if unknown."""

        return self._by_name.get(name)

    def require(self, name: str) -> ToolSpec:
        """Return the spec for `name`, or raise `KeyError`."""

        spec = self._by_name.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    @property
    def _by_name(self) -> Mapping[str, ToolSpec]:
        return {spec.name: spec for spec in self.specs}


# === Evidence Tool Specs ===

# Filter schemas
_LOCATION_FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "role": {
            "type": "string",
            "enum": ["recipient", "place_of_performance"],
        },
        "location_ids": {"type": "array", "items": {"type": "string"}},
        "country_code": {"type": "string"},
        "state_code": {"type": "string"},
        "county_fips": {"type": "string"},
        "city_name": {"type": "string"},
        "zip_code": {"type": "string"},
    },
    "required": ["role"],
    "additionalProperties": False,
}
_AWARD_FILTERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "award_ids": {"type": "array", "items": {"type": "string"}},
        "recipient_ids": {"type": "array", "items": {"type": "string"}},
        "awarding_agency_ids": {"type": "array", "items": {"type": "string"}},
        "awarding_sub_agency_ids": {"type": "array", "items": {"type": "string"}},
        "awarding_office_ids": {"type": "array", "items": {"type": "string"}},
        "funding_agency_ids": {"type": "array", "items": {"type": "string"}},
        "funding_sub_agency_ids": {"type": "array", "items": {"type": "string"}},
        "funding_office_ids": {"type": "array", "items": {"type": "string"}},
        "parent_idv_ids": {"type": "array", "items": {"type": "string"}},
        "naics_ids": {"type": "array", "items": {"type": "string"}},
        "psc_ids": {"type": "array", "items": {"type": "string"}},
        "location": _LOCATION_FILTER_SCHEMA,
    },
    "additionalProperties": False,
}

# Tool definitions
EVIDENCE_TOOLS: ToolDefinitions = ToolDefinitions(
    specs=(
        ToolSpec(
            name="search_contract_work",
            description=(
                "Semantic search over contract-work text. Returns a SelectionRef plus bounded semantic hits. Pass candidates to restrict to a prior SelectionRef."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "min_score": {"type": "number"},
                    "candidates": {
                        "type": "string",
                        "description": "Opaque SelectionRef id from a prior tool result",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="resolve_awards",
            description=(
                "Resolve Awards with structured filters into a SelectionRef, with a bounded AwardCard preview."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filters": _AWARD_FILTERS_SCHEMA,
                    "preview_limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="aggregate_activity",
            description=(
                "Deterministically aggregate obligations for a SelectionRef inside an inclusive activity date window. Use for totals, rankings, and counts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selection": {
                        "type": "string",
                        "description": "Opaque SelectionRef id",
                    },
                    "window": {
                        "type": "object",
                        "properties": {
                            "from_date": {
                                "type": "string",
                                "description": "ISO date YYYY-MM-DD",
                            },
                            "to_date": {
                                "type": "string",
                                "description": "ISO date YYYY-MM-DD",
                            },
                        },
                        "required": ["from_date", "to_date"],
                        "additionalProperties": False,
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["award", "recipient"],
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["selection", "window"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="traverse_relationships",
            description=(
                "One-hop related entities for a SelectionRef (recipients, agencies, offices, IDVs, locations, classifications)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selection": {"type": "string"},
                    "include": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "recipient",
                                "agency",
                                "office",
                                "idv",
                                "location",
                                "classification",
                            ],
                        },
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["selection"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="get_award_evidence",
            description=(
                "Load bounded Award citation cards from exactly one of: a SelectionRef (first limit awards by award_id ASC) or an explicit award_ids list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "selection": {"type": "string"},
                    "award_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        ),
    )
)

SUBMIT_ANSWER_TOOL: ToolSpec = ToolSpec(
    name="submit_answer",
    description=(
        "Terminate the run with a final natural-language answer and citation Award IDs that were acquired as Award cards in this session. Unknown citation IDs are dropped."
    ),
    parameters={
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citation_award_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["answer", "citation_award_ids"],
        "additionalProperties": False,
    },
)

AGENT_TOOLS: ToolDefinitions = ToolDefinitions(
    specs=(*EVIDENCE_TOOLS.specs, SUBMIT_ANSWER_TOOL),
)
"""Evidence tools plus the orchestration-terminal `submit_answer` tool."""
