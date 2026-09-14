# cy_th/agent/dispatch.py

"""Dispatch `ToolCall`s onto an `EvidenceSession`.

Turns model-requested tool invocations into bounded JSON observations. Evidence failures become `ok: false` payloads (not raised), so an orchestration loop can feed them back as `MessageRole.TOOL` content.
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence
import json

from cy_th.agent.tools import EVIDENCE_TOOLS
from cy_th.agent.types import Message, MessageRole, ToolCall
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


# === Result ===

@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of one dispatched tool call (success or bounded error observation)."""

    call_id: str
    name: str
    ok: bool
    data: Mapping[str, Any]

    @property
    def content(self) -> str:
        """JSON text suitable for `Message.content` on a tool turn."""

        return json.dumps(self.data, ensure_ascii=False, default=str)

    def as_message(self) -> Message:
        """Provider-neutral tool observation message for conversation append."""

        return Message(
            role=MessageRole.TOOL,
            content=self.content,
            tool_call_id=self.call_id,
            name=self.name,
        )


# === Dispatch ===

def dispatch_tool(session: EvidenceSession, call: ToolCall) -> ToolResult:
    """Run one `ToolCall` against `session` and return a JSON-ready observation.

    Unknown tools and evidence/argument failures become `ok: false` results.
    """

    handler = _HANDLERS.get(call.name)
    if handler is None:
        known = ", ".join(sorted(EVIDENCE_TOOLS.names))
        return _failure(
            call,
            error="UnknownTool",
            detail=f"unknown tool {call.name!r}; known: {known}",
        )

    try:
        view_dict = handler(session, dict(call.arguments))
    except EvidenceError as exc:
        return _failure(call, error=type(exc).__name__, detail=str(exc))
    except (TypeError, ValueError, KeyError) as exc:
        return _failure(call, error=type(exc).__name__, detail=str(exc))

    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        data={"ok": True, "result": view_dict},
    )

def dispatch_tools(
    session: EvidenceSession,
    calls: Sequence[ToolCall],
) -> tuple[ToolResult, ...]:
    """Dispatch tool calls in order (sequential; session state may accumulate)."""

    return tuple(dispatch_tool(session, call) for call in calls)


# === Handlers ===

def _search_contract_work(session: EvidenceSession, args: dict[str, Any]) -> dict[str, Any]:
    query = _require_str(args, "query")
    top_k = _optional_int(args, "top_k")
    min_score = _optional_float(args, "min_score")
    candidates_raw = args.get("candidates")
    candidates = (
        None if candidates_raw is None else SelectionRef(_require_str_value(candidates_raw, "candidates"))
    )

    kwargs: dict[str, Any] = {}
    if top_k is not None:
        kwargs["top_k"] = top_k
    if min_score is not None:
        kwargs["min_score"] = min_score
    if candidates is not None:
        kwargs["candidates"] = candidates

    return session.search_contract_work(query, **kwargs).to_dict()

def _resolve_awards(session: EvidenceSession, args: dict[str, Any]) -> dict[str, Any]:
    filters_raw = args.get("filters")
    filters = None if filters_raw is None else _parse_award_filters(filters_raw)
    preview_limit = _optional_int(args, "preview_limit")

    kwargs: dict[str, Any] = {}
    if preview_limit is not None:
        kwargs["preview_limit"] = preview_limit
    return session.resolve_awards(filters, **kwargs).to_dict()

def _aggregate_activity(session: EvidenceSession, args: dict[str, Any]) -> dict[str, Any]:
    selection = SelectionRef(_require_str(args, "selection"))
    window = _parse_activity_window(_require_mapping(args, "window"))
    group_by_raw = args.get("group_by")
    limit = _optional_int(args, "limit")

    kwargs: dict[str, Any] = {}
    if group_by_raw is not None:
        kwargs["group_by"] = GroupBy(_require_str_value(group_by_raw, "group_by"))
    if limit is not None:
        kwargs["limit"] = limit
    return session.aggregate_activity(selection, window, **kwargs).to_dict()

def _traverse_relationships(session: EvidenceSession, args: dict[str, Any]) -> dict[str, Any]:
    selection = SelectionRef(_require_str(args, "selection"))
    include_raw = args.get("include")
    limit = _optional_int(args, "limit")

    kwargs: dict[str, Any] = {}
    if include_raw is not None:
        if not isinstance(include_raw, Sequence) or isinstance(include_raw, (str, bytes)):
            raise TypeError("include must be an array of entity kind strings")
        kwargs["include"] = [EntityKind(_require_str_value(item, "include[]")) for item in include_raw]
    if limit is not None:
        kwargs["limit"] = limit
    return session.traverse_relationships(selection, **kwargs).to_dict()

def _get_award_evidence(session: EvidenceSession, args: dict[str, Any]) -> dict[str, Any]:
    selection_raw = args.get("selection")
    award_ids_raw = args.get("award_ids")
    limit = _optional_int(args, "limit")

    selection = (
        None
        if selection_raw is None
        else SelectionRef(_require_str_value(selection_raw, "selection"))
    )
    award_ids: list[str] | None
    if award_ids_raw is None:
        award_ids = None
    else:
        if not isinstance(award_ids_raw, Sequence) or isinstance(award_ids_raw, (str, bytes)):
            raise TypeError("award_ids must be an array of strings")
        award_ids = [_require_str_value(item, "award_ids[]") for item in award_ids_raw]

    kwargs: dict[str, Any] = {"selection": selection, "award_ids": award_ids}
    if limit is not None:
        kwargs["limit"] = limit
    return session.get_award_evidence(**kwargs).to_dict()


# Tool handlers mapping
_HANDLERS: Mapping[str, Callable[[EvidenceSession, dict[str, Any]], dict[str, Any]]] = {
    "search_contract_work": _search_contract_work,
    "resolve_awards": _resolve_awards,
    "aggregate_activity": _aggregate_activity,
    "traverse_relationships": _traverse_relationships,
    "get_award_evidence": _get_award_evidence,
}


# === Arg Parsing ===

def _parse_award_filters(raw: object) -> AwardFilters:
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

def _parse_activity_window(raw: Mapping[str, Any]) -> ActivityWindow:
    from_date = date.fromisoformat(_require_str(raw, "from_date"))
    to_date = date.fromisoformat(_require_str(raw, "to_date"))
    return ActivityWindow(from_date=from_date, to_date=to_date)


# === Scalars / Containers ===

def _failure(call: ToolCall, *, error: str, detail: str) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        data={"ok": False, "error": error, "detail": detail},
    )

def _require_mapping(args: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = args.get(key)
    if value is None:
        raise KeyError(f"missing required argument {key!r}")
    return _as_mapping(value, key)

def _as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value

def _require_str(args: Mapping[str, Any], key: str) -> str:
    if key not in args or args[key] is None:
        raise KeyError(f"missing required argument {key!r}")
    return _require_str_value(args[key], key)

def _require_str_value(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must be non-empty")
    return value

def _optional_str(args: Mapping[str, Any], key: str) -> str | None:
    if key not in args or args[key] is None:
        return None
    return _require_str_value(args[key], key)

def _optional_int(args: Mapping[str, Any], key: str) -> int | None:
    if key not in args or args[key] is None:
        return None
    value = args[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value

def _optional_float(args: Mapping[str, Any], key: str) -> float | None:
    if key not in args or args[key] is None:
        return None
    value = args[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be a number")
    return float(value)

def _optional_str_list(args: Mapping[str, Any], key: str) -> list[str] | None:
    if key not in args or args[key] is None:
        return None
    value = args[key]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{key} must be an array of strings")
    return [_require_str_value(item, f"{key}[]") for item in value]
