# cy_th/agent/provider.py

"""Provider-neutral model client protocol.

Providers plug in by implementing `ModelClient`.

#### Current Adapters:
    - `OpenAIResponsesClient`: OpenAI Responses API function tools
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable
import json
import os

from cy_th.agent.errors import MissingModelKeyError
from cy_th.agent.tools import ToolDefinition
from cy_th.agent.types import DEFAULT_MODEL


# === Tool Choice ===

class ToolChoiceMode(StrEnum):
    """How the model may / must use tools on a turn."""

    AUTO = "auto"
    REQUIRED = "required"

@dataclass(frozen=True, slots=True)
class ToolChoice:
    """Provider-neutral tool-choice directive."""

    mode: ToolChoiceMode = ToolChoiceMode.AUTO
    tool_name: str | None = None  # When set with REQUIRED, force that tool


# === Turn Types ===

@dataclass(frozen=True, slots=True)
class ToolCall:
    """One model-requested function invocation."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ToolResult:
    """Observation returned for a prior `ToolCall`."""

    call_id: str
    output: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One model turn in provider-neutral form.

    Providers may use `previous_response_id` for stateful chaining. When absent, `input_text` carries the user question (typically the first turn). Tool results are always supplied explicitly for the calls being answered.
    """

    instructions: str
    tools: tuple[ToolDefinition, ...]
    tool_choice: ToolChoice = ToolChoice()
    input_text: str | None = None
    previous_response_id: str | None = None
    tool_results: tuple[ToolResult, ...] = ()

@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Provider-neutral model turn result."""

    response_id: str
    tool_calls: tuple[ToolCall, ...]


# === Protocol ===

@runtime_checkable
class ModelClient(Protocol):
    """Pluggable model backend used by `ProcurementAgent`."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Run one model turn and return any requested tool calls."""
        ...


# === Adapters ===

class OpenAIResponsesClient:
    """`ModelClient` backed by the OpenAI Responses API (function tools).

    Env:
        - `OPENAI_API_KEY` (required)
        - `CYTH_MODEL` (optional; default `DEFAULT_MODEL`)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: object | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if client is None and not key:
            raise MissingModelKeyError("OPENAI_API_KEY is not set")

        self._model = model or os.environ.get("CYTH_MODEL", DEFAULT_MODEL)
        if client is not None:
            self._client = client
        else:
            self._client = _build_openai_client(api_key=key)

    @classmethod
    def from_env(cls) -> OpenAIResponsesClient:
        """Construct from `OPENAI_API_KEY` / `CYTH_MODEL`."""

        return cls()

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": request.instructions,
            "tools": [_openai_tool(t) for t in request.tools],
            "tool_choice": _openai_tool_choice(request.tool_choice),
        }

        if request.previous_response_id is not None:
            kwargs["previous_response_id"] = request.previous_response_id

        input_items = _openai_input_items(request)
        if input_items:
            kwargs["input"] = input_items

        response = self._client.responses.create(**kwargs)  # type: ignore[attr-defined]
        response_id = str(getattr(response, "id", "") or "")
        tool_calls = tuple(_extract_openai_tool_calls(response))
        return ModelResponse(response_id=response_id, tool_calls=tool_calls)


# === OpenAI Helpers ===

def _build_openai_client(*, api_key: str | None) -> object:
    try:
        from importlib import import_module

        module = import_module("openai")
        openai_cls = getattr(module, "OpenAI")
    except ImportError as exc:
        raise RuntimeError(
            "openai package is not installed; install with: "
            "uv sync --extra agent  (or pip install 'cy-th[agent]')"
        ) from exc
    return openai_cls(api_key=api_key)

def _openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": dict(tool.parameters),
    }

def _openai_tool_choice(choice: ToolChoice) -> Any:
    if choice.mode is ToolChoiceMode.AUTO:
        return "auto"
    if choice.tool_name:
        return {"type": "function", "name": choice.tool_name}
    return "required"

def _openai_input_items(request: ModelRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if request.input_text is not None:
        items.append(
            {
                "role": "user",
                "content": request.input_text,
            }
        )
    for result in request.tool_results:
        items.append(
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": json.dumps(result.output),
            }
        )
    return items

def _extract_openai_tool_calls(response: object) -> list[ToolCall]:
    output = getattr(response, "output", None) or []
    calls: list[ToolCall] = []
    for item in output:
        call_id, name, raw_args = _openai_function_call_fields(item)
        if call_id is None or name is None:
            continue
        if isinstance(raw_args, Mapping):
            arguments: Mapping[str, Any] = dict(raw_args)
        else:
            try:
                parsed = json.loads(str(raw_args or "{}"))
            except json.JSONDecodeError:
                parsed = {}
            arguments = parsed if isinstance(parsed, dict) else {}
        calls.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
    return calls

def _openai_function_call_fields(
    item: object,
) -> tuple[str | None, str | None, object]:
    if isinstance(item, Mapping):
        if item.get("type") != "function_call":
            return None, None, None
        call_id = str(item.get("call_id") or item.get("id") or "")
        name = str(item.get("name") or "")
        return call_id, name, item.get("arguments")

    if getattr(item, "type", None) != "function_call":
        return None, None, None
    call_id = str(getattr(item, "call_id", None) or getattr(item, "id", "") or "")
    name = str(getattr(item, "name", "") or "")
    return call_id, name, getattr(item, "arguments", None)
