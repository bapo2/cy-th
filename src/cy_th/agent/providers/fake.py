# cy_th/agent/providers/fake.py

"""Scripted offline `ModelSession` for tests and local orchestration dry-runs."""

# === Imports ===

from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Callable, Sequence

from cy_th.agent.errors import AgentError, ClosedModelSessionError
from cy_th.agent.types import (
    Conversation,
    ModelResponse,
    ToolSpec,
    TurnPolicy,
)


# === Types ===

FakeResponder = Callable[
    [Conversation, Sequence[ToolSpec], TurnPolicy],
    ModelResponse,
]
"""Turn handler: `(conversation, tools, policy) → ModelResponse`."""

FakeScriptItem = ModelResponse | FakeResponder
"""One queued turn: Fixed response or callable responder."""

@dataclass(frozen=True, slots=True)
class FakeCompleteCall:
    """One recorded `complete` invocation (inputs as passed after policy defaulting)."""

    conversation: Conversation
    tools: tuple[ToolSpec, ...]
    policy: TurnPolicy


# === Errors ===

class ExhaustedFakeResponsesError(AgentError):
    """Raised when `complete` is called with an empty script queue."""

    def __init__(self, detail: str = "FakeModelSession has no remaining scripted responses") -> None:
        self.detail = detail
        super().__init__(detail)


# === Session ===

class FakeModelSession:
    """Offline `ModelSession` that returns scripted `ModelResponse` values in order.

    #### Conventions:
        - Queue items may be `ModelResponse` or `FakeResponder` callables
        - `calls` records every successful `complete` (after policy defaulting)
        - `close` invalidates further `complete` calls
    """

    def __init__(self, responses: Sequence[FakeScriptItem] = ()) -> None:
        self._queue: deque[FakeScriptItem] = deque(responses)
        self._closed = False
        self._calls: list[FakeCompleteCall] = []

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def remaining(self) -> int:
        """Number of scripted responses still queued."""

        return len(self._queue)

    @property
    def calls(self) -> tuple[FakeCompleteCall, ...]:
        """Successful `complete` invocations in order."""

        return tuple(self._calls)

    def enqueue(self, *responses: FakeScriptItem) -> None:
        """Append more scripted turns (must not be closed)."""

        self._ensure_open()
        self._queue.extend(responses)

    def complete(
        self,
        conversation: Conversation,
        tools: Sequence[ToolSpec] = (),
        *,
        policy: TurnPolicy | None = None,
    ) -> ModelResponse:
        """Pop the next scripted response (or invoke the next responder)."""

        self._ensure_open()
        if not self._queue:
            raise ExhaustedFakeResponsesError()

        resolved = policy if policy is not None else TurnPolicy()
        tools_tuple = tuple(tools)
        self._calls.append(
            FakeCompleteCall(
                conversation=conversation,
                tools=tools_tuple,
                policy=resolved,
            )
        )

        item = self._queue.popleft()
        if isinstance(item, ModelResponse):
            return item
        return item(conversation, tools_tuple, resolved)

    def close(self) -> None:
        """Mark the session closed; further `complete` / `enqueue` calls fail."""

        self._closed = True
        self._queue.clear()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedModelSessionError()
