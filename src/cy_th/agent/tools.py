# cy_th/agent/tools.py

"""JSON tool schemas and dispatch onto `EvidenceSession` (+ `submit_answer`)."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping
import json

from cy_th.agent.errors import InvalidAgentRequestError
from cy_th.evidence.errors import EvidenceError
from cy_th.evidence.session import EvidenceSession
from cy_th.evidence.types import SelectionRef
from cy_th.query.types import (
    ActivityWindow,
    AwardFilters,
    EntityKind,
    GroupBy,
    LocationFilter,
    RelationRole,
)


# === Constants ===

SUBMIT_ANSWER: str = "submit_answer"

PROCUREMENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_contract_work",
        "resolve_awards",
        "aggregate_activity",
        "traverse_relationships",
        "get_award_evidence",
    }
)


# === Schemas ===

@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One callable tool description (JSON Schema parameters)."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }

def tool_definitions(
    *,
    include_procurement: bool = True,
    include_submit: bool = True,
) -> tuple[ToolDefinition, ...]:
    """Return tool schemas for a model turn."""

    tools: list[ToolDefinition] = []
    if include_procurement:
        tools.extend(_PROCUREMENT_DEFINITIONS)
    if include_submit:
        tools.append(_SUBMIT_DEFINITION)
    return tuple(tools)


# === Dispatch ===

@dataclass(frozen=True, slots=True)
class SubmitAnswerArgs:
    """Parsed `submit_answer` payload."""

    answer: str
    citation_award_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of one tool dispatch (procurement observation or submit)."""

    name: str
    arguments: Mapping[str, Any]
    ok: bool
    observation: Mapping[str, Any]
    submit: SubmitAnswerArgs | None = None

def dispatch_tool(
    session: EvidenceSession,
    name: str,
    arguments: Mapping[str, Any] | str | None,
) -> DispatchResult:
    """Parse args, run the tool, and return a bounded observation (or submit)."""

    try:
        args = _coerce_arguments(arguments)
    except InvalidAgentRequestError as exc:
        return DispatchResult(
            name=name,
            arguments={},
            ok=False,
            observation=_error_observation(type(exc).__name__, exc.detail),
        )

    if name == SUBMIT_ANSWER:
        try:
            submit = _parse_submit_answer(args)
        except InvalidAgentRequestError as exc:
            return DispatchResult(
                name=name,
                arguments=args,
                ok=False,
                observation=_error_observation(type(exc).__name__, exc.detail),
            )
        return DispatchResult(
            name=name,
            arguments=args,
            ok=True,
            observation={"status": "submitted"},
            submit=submit,
        )

    if name not in PROCUREMENT_TOOL_NAMES:
        return DispatchResult(
            name=name,
            arguments=args,
            ok=False,
            observation=_error_observation(
                "UnknownToolError", f"unknown tool {name!r}"
            ),
        )

    try:
        payload = _run_procurement(session, name, args)
    except EvidenceError as exc:
        return DispatchResult(
            name=name,
            arguments=args,
            ok=False,
            observation=_error_observation(type(exc).__name__, str(exc)),
        )
    except (InvalidAgentRequestError, ValueError, TypeError, KeyError) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return DispatchResult(
            name=name,
            arguments=args,
            ok=False,
            observation=_error_observation(type(exc).__name__, detail),
        )
    except Exception as exc:  # Unexpected; still make sure we don't invent evidence
        return DispatchResult(
            name=name,
            arguments=args,
            ok=False,
            observation=_error_observation(type(exc).__name__, str(exc)),
        )

    return DispatchResult(
        name=name,
        arguments=args,
        ok=True,
        observation=payload,
    )


# === Procurement Runners ===

def _run_procurement(
    session: EvidenceSession,
    name: str,
    args: Mapping[str, Any],
) -> dict[str, Any]:
    if name == "search_contract_work":
        query = _require_str(args, "query")
        kwargs: dict[str, Any] = {}
        if "top_k" in args and args["top_k"] is not None:
            kwargs["top_k"] = _as_int(args["top_k"], "top_k")
        if "min_score" in args and args["min_score"] is not None:
            kwargs["min_score"] = float(args["min_score"])
        if "candidates" in args and args["candidates"] is not None:
            kwargs["candidates"] = SelectionRef(id=_as_str(args["candidates"], "candidates"))
        return session.search_contract_work(query, **kwargs).to_dict()

    if name == "resolve_awards":
        filters = _parse_award_filters(args.get("filters"))
        kwargs = {}
        if "preview_limit" in args and args["preview_limit"] is not None:
            kwargs["preview_limit"] = _as_int(args["preview_limit"], "preview_limit")
        return session.resolve_awards(filters, **kwargs).to_dict()

    if name == "aggregate_activity":
        selection = SelectionRef(id=_require_str(args, "selection"))
        window = _parse_activity_window(_require_mapping(args, "window"))
        kwargs = {}
        if "group_by" in args and args["group_by"] is not None:
            kwargs["group_by"] = GroupBy(_as_str(args["group_by"], "group_by"))
        if "limit" in args and args["limit"] is not None:
            kwargs["limit"] = _as_int(args["limit"], "limit")
        return session.aggregate_activity(selection, window, **kwargs).to_dict()

    if name == "traverse_relationships":
        selection = SelectionRef(id=_require_str(args, "selection"))
        kwargs = {}
        if "include" in args and args["include"] is not None:
            kwargs["include"] = [
                EntityKind(_as_str(item, "include[]")) for item in _as_list(args["include"], "include")
            ]
        if "limit" in args and args["limit"] is not None:
            kwargs["limit"] = _as_int(args["limit"], "limit")
        return session.traverse_relationships(selection, **kwargs).to_dict()

    if name == "get_award_evidence":
        has_sel = args.get("selection") is not None
        has_ids = args.get("award_ids") is not None
        if has_sel == has_ids:
            raise InvalidAgentRequestError(
                "get_award_evidence requires exactly one of selection or award_ids"
            )
        kwargs = {}
        if has_sel:
            kwargs["selection"] = SelectionRef(id=_as_str(args["selection"], "selection"))
        else:
            kwargs["award_ids"] = [
                _as_str(item, "award_ids[]") for item in _as_list(args["award_ids"], "award_ids")
            ]
        if "limit" in args and args["limit"] is not None:
            kwargs["limit"] = _as_int(args["limit"], "limit")
        return session.get_award_evidence(**kwargs).to_dict()

    raise InvalidAgentRequestError(f"unknown procurement tool {name!r}")


# === Parsers ===

def _parse_submit_answer(args: Mapping[str, Any]) -> SubmitAnswerArgs:
    answer = _require_str(args, "answer").strip()
    if not answer:
        raise InvalidAgentRequestError("submit_answer.answer must be non-empty")
    raw_ids = args.get("citation_award_ids", [])
    if raw_ids is None:
        raw_ids = []
    ids = tuple(_as_str(item, "citation_award_ids[]") for item in _as_list(raw_ids, "citation_award_ids"))
    return SubmitAnswerArgs(answer=answer, citation_award_ids=ids)

def _parse_award_filters(raw: object) -> AwardFilters | None:
    if raw is None:
        return None
    data = _as_mapping(raw, "filters")
    location_raw = data.get("location")
    location = None if location_raw is None else _parse_location_filter(location_raw)
    return AwardFilters(
        award_ids=_optional_str_list(data, "award_ids"),
        recipient_ids=_optional_str_list(data, "recipient_ids"),
        awarding_agency_ids=_optional_str_list(data, "awarding_agency_ids"),
        awarding_sub_agency_ids=_optional_str_list(data, "awarding_sub_agency_ids"),
        awarding_office_ids=_optional_str_list(data, "awarding_office_ids"),
        funding_agency_ids=_optional_str_list(data, "funding_agency_ids"),
        funding_sub_agency_ids=_optional_str_list(data, "funding_sub_agency_ids"),
        funding_office_ids=_optional_str_list(data, "funding_office_ids"),
        parent_idv_ids=_optional_str_list(data, "parent_idv_ids"),
        naics_ids=_optional_str_list(data, "naics_ids"),
        psc_ids=_optional_str_list(data, "psc_ids"),
        location=location,
    )

def _parse_location_filter(raw: object) -> LocationFilter:
    data = _as_mapping(raw, "location")
    role = RelationRole(_require_str(data, "role"))
    return LocationFilter(
        role=role,
        location_ids=_optional_str_list(data, "location_ids"),
        country_code=_optional_str(data, "country_code"),
        state_code=_optional_str(data, "state_code"),
        county_fips=_optional_str(data, "county_fips"),
        city_name=_optional_str(data, "city_name"),
        zip_code=_optional_str(data, "zip_code"),
    )

def _parse_activity_window(data: Mapping[str, Any]) -> ActivityWindow:
    return ActivityWindow(
        from_date=_as_date(_require_str(data, "from_date"), "from_date"),
        to_date=_as_date(_require_str(data, "to_date"), "to_date"),
    )


# === Coercion Helpers ===

def _coerce_arguments(arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidAgentRequestError(f"invalid tool arguments JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise InvalidAgentRequestError("tool arguments must be a JSON object")
        return parsed
    return dict(arguments)

def _error_observation(error_type: str, detail: str) -> dict[str, str]:
    return {"error": error_type, "detail": detail}

def _require_str(data: Mapping[str, Any], key: str) -> str:
    if key not in data or data[key] is None:
        raise InvalidAgentRequestError(f"missing required field {key!r}")
    return _as_str(data[key], key)

def _require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in data or data[key] is None:
        raise InvalidAgentRequestError(f"missing required field {key!r}")
    return _as_mapping(data[key], key)

def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    if key not in data or data[key] is None:
        return None
    return _as_str(data[key], key)

def _optional_str_list(data: Mapping[str, Any], key: str) -> list[str] | None:
    if key not in data or data[key] is None:
        return None
    return [_as_str(item, f"{key}[]") for item in _as_list(data[key], key)]

def _as_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise InvalidAgentRequestError(f"{name} must be a string")
    return value

def _as_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAgentRequestError(f"{name} must be an integer")
    return value

def _as_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise InvalidAgentRequestError(f"{name} must be an array")
    return value

def _as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidAgentRequestError(f"{name} must be an object")
    return value

def _as_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidAgentRequestError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


# === Definition Bodies ===

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

_PROCUREMENT_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="search_contract_work",
        description=(
            "Semantic search over contract-work text. Returns a SelectionRef plus bounded semantic hits. Use candidates to restrict to a prior selection."
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
    ToolDefinition(
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
    ToolDefinition(
        name="aggregate_activity",
        description=(
            "Deterministically aggregate obligations for a SelectionRef inside an inclusive activity date window. Use this for totals, rankings, and counts."
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
                "group_by": {"type": "string", "enum": ["award", "recipient"]},
                "limit": {"type": "integer"},
            },
            "required": ["selection", "window"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
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
    ToolDefinition(
        name="get_award_evidence",
        description=(
            "Load bounded Award citation cards from exactly one SelectionRef (first limit awards by award_id ASC) or an explicit award_ids list."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selection": {"type": "string"},
                "award_ids": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ),
)

_SUBMIT_DEFINITION = ToolDefinition(
    name=SUBMIT_ANSWER,
    description=(
        "Terminate the run with a final natural-language answer and citation Award IDs acquired as Award cards in this session."
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
