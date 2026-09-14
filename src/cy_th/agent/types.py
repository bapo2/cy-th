# cy_th/agent/types.py

"""Provider-neutral conversation and tool types for model sessions.

Cy-TH owns conversation history in these shapes. Provider adapters translate to/from vendor APIs (provider-native handles private to adapters).
"""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence


# === Enums ===

class MessageRole(StrEnum):
    """Role of one turn in a Cy-TH conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class ToolChoiceMode(StrEnum):
    """How the model may use tools on a turn."""

    AUTO = "auto"
    NONE = "none"
    REQUIRED = "required"
    # Force a specific tool via `TurnPolicy.tool_name`


# === Tools ===

@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One callable tool description (JSON Schema `parameters`)."""

    name: str
    description: str
    parameters: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ToolCall:
    """One model-requested tool invocation (arguments already parsed)."""

    id: str
    name: str
    arguments: Mapping[str, Any]


# === Conversation ===

@dataclass(frozen=True, slots=True)
class Message:
    """One provider-neutral conversation message.

    #### Conventions:
        - `user`: `content` set; `tool_calls` / `tool_call_id` / `name` unused
        - `assistant`: optional `content` (prose) and/or `tool_calls`
        - `tool`: result for a prior call; `tool_call_id` (+ usually `name`) and `content` holding the observation payload as text (typically JSON)
    """

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

Conversation = Sequence[Message]
"""Ordered Cy-TH-owned conversation history (append-only from the orchestrator's view)."""


# === Turn Policy / Response ===

@dataclass(frozen=True, slots=True)
class TurnPolicy:
    """Per-turn controls shared across providers.

    #### Conventions:
        - When `tool_choice` is `REQUIRED` and `tool_name` is set, the model must call that tool
        - When `tool_choice` is `REQUIRED` and `tool_name` is `None`, any tool is acceptable
    """

    tool_choice: ToolChoiceMode = ToolChoiceMode.AUTO
    tool_name: str | None = None

@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Provider-neutral model turn result after inbound translation."""

    prose: str | None
    tool_calls: tuple[ToolCall, ...] = ()
