# cy_th/agent/protocol.py

"""Provider-neutral `ModelSession` protocol.

Adapters (OpenAI, Anthropic, ...) implement this interface. Adapters translate Cy-TH conversation + tool specs outbound, call the vendor API, and translate inbound into `ModelResponse`. Provider-native handles stay private to the adapter.
"""

# === Imports ===

from __future__ import annotations
from typing import Protocol, Sequence, runtime_checkable

from cy_th.agent.types import (
    Conversation,
    ModelResponse,
    ToolSpec,
    TurnPolicy,
)


# === Protocol ===

@runtime_checkable
class ModelSession(Protocol):
    """One model-backed session that accepts Cy-TH conversation state.

    Cy-TH owns the `Conversation` and appends user / assistant / tool messages. Each `complete` call passes the current history plus available tools; the adapter may keep private provider state across calls (e.g. response IDs).
    """

    def complete(
        self,
        conversation: Conversation,
        tools: Sequence[ToolSpec] = (),
        *,
        policy: TurnPolicy | None = None,
    ) -> ModelResponse:
        """Run one model turn over `conversation` with optional `tools`.

        When `policy` is `None`, adapters should treat it as `TurnPolicy()` (auto tool choice).
        """
        ...

    def close(self) -> None:
        """Release provider resources; further `complete` calls are invalid."""
        ...
