# cy_th/agent/providers/openai.py

"""OpenAI Responses API adapter for `ModelSession`.

#### Usage:
    Install the optional extra only when you need this adapter:
        ```
        uv sync --extra openai
        # or: pip install 'cy-th[openai]'
        ```

    Then:
        ```python
        from cy_th.agent.providers.openai import OpenAIModelSession

        with_session = OpenAIModelSession.from_env()
        # or: OpenAIModelSession(model="gpt-4.1-mini", api_key="...")
        ```

Importing this module does not require the `openai` package; constructing `OpenAIModelSession` does (lazy import).
"""

# === Imports ===

from __future__ import annotations
from typing import Any, Mapping, Sequence
import json
import os

from cy_th.agent.errors import (
    ClosedModelSessionError,
    InvalidModelRequestError,
    MissingModelKeyError,
    MissingOpenAIDepsError,
)
from cy_th.agent.types import (
    Conversation,
    Message,
    MessageRole,
    ModelResponse,
    ToolCall,
    ToolChoiceMode,
    ToolSpec,
    TurnPolicy,
)


# === Constants ===

DEFAULT_MODEL: str = "gpt-4.1-mini"
"""Default Responses model when neither ctor `model=` nor `CYTH_MODEL` is set."""

ENV_API_KEY: str = "OPENAI_API_KEY"
ENV_MODEL: str = "CYTH_MODEL"


# === Dep Gate ===

def require_openai() -> Any:
    """Import the `openai` package or raise `MissingOpenAIDepsError`.

    #### Returns:
        The imported `openai` module.
    """

    try:
        from importlib import import_module

        return import_module("openai")
    except ImportError as exc:
        raise MissingOpenAIDepsError() from exc


# === Session ===

class OpenAIModelSession:
    """`ModelSession` backed by the OpenAI Responses API.

    #### Conventions:
        - Optional dep: Requires `cy-th[openai]` (see module docstring)
        - Pass `client=` to inject a pre-built SDK client (tests / custom transport)
        - `instructions` are sent on every `complete` (Responses does not inherit them via `previous_response_id`)
        - Conversation is treated as append-only for the life of this session
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        instructions: str | None = None,
        client: Any | None = None,
    ) -> None:
        openai = require_openai()
        resolved_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
        if client is None and not resolved_key:
            raise MissingModelKeyError(env_var=ENV_API_KEY)

        self._model = model if model is not None else os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._instructions = instructions
        self._owns_client = client is None
        self._client = client if client is not None else openai.OpenAI(api_key=resolved_key)

        self._closed = False
        self._previous_response_id: str | None = None
        self._synced_len: int = 0
        self._last_response: ModelResponse | None = None

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        instructions: str | None = None,
    ) -> OpenAIModelSession:
        """Build a session from `OPENAI_API_KEY` and optional `CYTH_MODEL`."""

        return cls(model=model, instructions=instructions)

    @property
    def model(self) -> str:
        return self._model

    @property
    def closed(self) -> bool:
        return self._closed

    def complete(
        self,
        conversation: Conversation,
        tools: Sequence[ToolSpec] = (),
        *,
        policy: TurnPolicy | None = None,
    ) -> ModelResponse:
        """Translate Cy-TH state → Responses `create`, then inbound → `ModelResponse`."""

        self._ensure_open()
        resolved = policy if policy is not None else TurnPolicy()
        delta = self._delta_messages(conversation)
        input_items = _to_input_items(
            delta,
            include_assistant_tool_calls=self._previous_response_id is None,
        )
        if not input_items:
            raise InvalidModelRequestError(
                "no new conversation items to send (empty conversation or nothing since last complete)"
            )

        kwargs: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
        }
        if self._instructions is not None:
            kwargs["instructions"] = self._instructions
        if self._previous_response_id is not None:
            kwargs["previous_response_id"] = self._previous_response_id

        tool_payloads = [_to_function_tool(spec) for spec in tools]
        if tool_payloads:
            kwargs["tools"] = tool_payloads
            kwargs["tool_choice"] = _to_tool_choice(resolved)
        elif resolved.tool_choice != ToolChoiceMode.AUTO:
            raise InvalidModelRequestError(
                "TurnPolicy.tool_choice requires tools when not AUTO"
            )

        raw = self._client.responses.create(**kwargs)
        parsed = _from_response(raw)
        response_id = getattr(raw, "id", None)
        if not isinstance(response_id, str) or not response_id:
            raise InvalidModelRequestError("OpenAI response missing id")

        self._previous_response_id = response_id
        self._synced_len = len(conversation)
        self._last_response = parsed
        return parsed

    def close(self) -> None:
        """Mark closed and release the SDK client when we own it."""

        self._closed = True
        self._previous_response_id = None
        self._last_response = None
        if self._owns_client:
            closer = getattr(self._client, "close", None)
            if callable(closer):
                closer()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedModelSessionError()

    def _delta_messages(self, conversation: Conversation) -> list[Message]:
        """Messages not yet absorbed by the provider, skipping last-response echo."""

        if self._synced_len > len(conversation):
            raise InvalidModelRequestError(
                "conversation shrank since last complete; OpenAIModelSession expects append-only history"
            )

        start = self._synced_len
        if (
            self._last_response is not None
            and start < len(conversation)
            and _mirrors_last_assistant(conversation[start], self._last_response)
        ):
            start += 1
        return list(conversation[start:])


# === Outbound / Inbound Translation ===

def _to_function_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "parameters": dict(spec.parameters),
        "strict": False,
    }

def _to_tool_choice(policy: TurnPolicy) -> Any:
    mode = policy.tool_choice
    if mode is ToolChoiceMode.AUTO:
        return "auto"
    if mode is ToolChoiceMode.NONE:
        return "none"
    if mode is ToolChoiceMode.REQUIRED:
        if policy.tool_name:
            return {"type": "function", "name": policy.tool_name}
        return "required"
    raise InvalidModelRequestError(f"unsupported ToolChoiceMode: {mode!r}")

def _to_input_items(
    messages: Sequence[Message],
    *,
    include_assistant_tool_calls: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role is MessageRole.USER:
            items.append({"role": "user", "content": msg.content or ""})
            continue

        if msg.role is MessageRole.ASSISTANT:
            if msg.tool_calls and include_assistant_tool_calls:
                for call in msg.tool_calls:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call.id,
                            "name": call.name,
                            "arguments": json.dumps(dict(call.arguments)),
                        }
                    )
            if msg.content:
                items.append({"role": "assistant", "content": msg.content})
            continue

        if msg.role is MessageRole.TOOL:
            if not msg.tool_call_id:
                raise InvalidModelRequestError("tool message missing tool_call_id")
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": msg.content or "",
                }
            )
            continue

        raise InvalidModelRequestError(f"unsupported message role: {msg.role!r}")
    return items

def _from_response(raw: Any) -> ModelResponse:
    prose = _extract_prose(raw)
    calls = tuple(_extract_tool_calls(raw))
    return ModelResponse(prose=prose, tool_calls=calls)

def _extract_prose(raw: Any) -> str | None:
    text = getattr(raw, "output_text", None)
    if isinstance(text, str) and text:
        return text

    chunks: list[str] = []
    for item in getattr(raw, "output", None) or []:
        item_type = _item_type(item)
        if item_type != "message":
            continue
        for part in getattr(item, "content", None) or []:
            part_type = _item_type(part)
            if part_type in {"output_text", "text"}:
                value = getattr(part, "text", None)
                if isinstance(value, str) and value:
                    chunks.append(value)
    if not chunks:
        return None
    return "".join(chunks)

def _extract_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in getattr(raw, "output", None) or []:
        if _item_type(item) != "function_call":
            continue
        call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
        name = getattr(item, "name", None)
        if not isinstance(call_id, str) or not isinstance(name, str):
            continue
        raw_args = getattr(item, "arguments", None)
        calls.append(ToolCall(id=call_id, name=name, arguments=_parse_arguments(raw_args)))
    return calls

def _parse_arguments(raw_args: object) -> Mapping[str, Any]:
    if isinstance(raw_args, Mapping):
        return dict(raw_args)
    try:
        parsed = json.loads(str(raw_args or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _item_type(item: object) -> str | None:
    value = getattr(item, "type", None)
    return value if isinstance(value, str) else None

def _mirrors_last_assistant(message: Message, response: ModelResponse) -> bool:
    if message.role is not MessageRole.ASSISTANT:
        return False
    if (message.content or "") != (response.prose or ""):
        return False
    if len(message.tool_calls) != len(response.tool_calls):
        return False
    for left, right in zip(message.tool_calls, response.tool_calls, strict=True):
        if left.id != right.id or left.name != right.name:
            return False
        if dict(left.arguments) != dict(right.arguments):
            return False
    return True
