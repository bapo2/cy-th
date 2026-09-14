# cy_th/agent/agent.py

"""Bounded procurement agent loop over `EvidenceSession` + `ModelSession`."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from cy_th.agent.dispatch import ToolResult, dispatch_tool
from cy_th.agent.errors import ClosedAgentError, InvalidAgentRequestError
from cy_th.agent.prompts import (
    BUDGET_EXHAUSTED_USER_MESSAGE,
    NO_TOOL_CALL_USER_MESSAGE,
)
from cy_th.agent.protocol import ModelSession
from cy_th.agent.submit import (
    SUBMIT_ANSWER,
    AgentAnswer,
    SubmittedAnswer,
    TerminationReason,
    ToolTraceEntry,
)
from cy_th.agent.tools import AGENT_TOOLS, EVIDENCE_TOOLS, SUBMIT_ANSWER_TOOL
from cy_th.agent.types import (
    Message,
    MessageRole,
    ModelResponse,
    ToolCall,
    ToolChoiceMode,
    TurnPolicy,
)
from cy_th.evidence.session import EvidenceSession


# === Budgets ===

DEFAULT_MAX_ROUNDS: int = 6
HARD_MAX_ROUNDS: int = 10

DEFAULT_MAX_TOOL_CALLS: int = 12
HARD_MAX_TOOL_CALLS: int = 24


def clamp_budget(value: int, *, hard_max: int, name: str) -> int:
    """Reject non-positive budgets; clamp to `hard_max`."""

    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return min(value, hard_max)


# === Agent ===

@dataclass(slots=True)
class ProcurementAgent:
    """Question-scoped agent that acquires evidence via tools then submits an answer.

    Evidence reaches the model through tool observations (and provider conversation chaining). Standing prompt text in `prompts.py`.
    """

    _session: EvidenceSession
    _model: ModelSession
    _max_rounds: int = DEFAULT_MAX_ROUNDS
    _max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    _closed: bool = False

    @classmethod
    def open(
        cls,
        data_root: Path | str | None = None,
        *,
        model_session: ModelSession,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    ) -> Self:
        """Open an evidence session and bind an injected `ModelSession`.

        The caller owns `model_session` lifecycle (this agent does not close it).
        """

        try:
            rounds = clamp_budget(max_rounds, hard_max=HARD_MAX_ROUNDS, name="max_rounds")
            tools = clamp_budget(
                max_tool_calls, hard_max=HARD_MAX_TOOL_CALLS, name="max_tool_calls"
            )
        except ValueError as exc:
            raise InvalidAgentRequestError(str(exc)) from exc

        return cls(
            _session=EvidenceSession.open(data_root),
            _model=model_session,
            _max_rounds=rounds,
            _max_tool_calls=tools,
        )

    @property
    def session(self) -> EvidenceSession:
        self._ensure_open()
        return self._session

    @property
    def max_rounds(self) -> int:
        return self._max_rounds

    @property
    def max_tool_calls(self) -> int:
        return self._max_tool_calls

    def answer(self, question: str) -> AgentAnswer:
        """Run the bounded tool loop for one user question."""

        self._ensure_open()
        text = question.strip()
        if not text:
            raise InvalidAgentRequestError("question must be non-empty")

        conversation: list[Message] = [
            Message(role=MessageRole.USER, content=text),
        ]
        rounds = 0
        tool_calls = 0
        trace: list[ToolTraceEntry] = []

        try:
            while True:
                if rounds >= self._max_rounds or tool_calls >= self._max_tool_calls:
                    return self._forced_submit(
                        conversation,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

                response = self._model.complete(
                    conversation,
                    tuple(AGENT_TOOLS),
                    policy=TurnPolicy(tool_choice=ToolChoiceMode.AUTO),
                )
                rounds += 1
                _append_assistant(conversation, response)

                if not response.tool_calls:
                    if rounds >= self._max_rounds or tool_calls >= self._max_tool_calls:
                        return self._forced_submit(
                            conversation,
                            rounds=rounds,
                            tool_calls=tool_calls,
                            trace=trace,
                        )
                    conversation.append(
                        Message(role=MessageRole.USER, content=NO_TOOL_CALL_USER_MESSAGE)
                    )
                    continue

                submitted: SubmittedAnswer | None = None
                for call in response.tool_calls:
                    if call.name == SUBMIT_ANSWER:
                        result = dispatch_tool(self._session, call)
                        trace.append(_trace_entry(rounds, call, result))
                        conversation.append(result.as_message())
                        if result.terminal and result.submitted is not None:
                            submitted = result.submitted
                            break
                        continue

                    if call.name in EVIDENCE_TOOLS.names:
                        if tool_calls >= self._max_tool_calls:
                            skipped = _budget_skip(call)
                            trace.append(_trace_entry(rounds, call, skipped))
                            conversation.append(skipped.as_message())
                            continue

                        result = dispatch_tool(self._session, call)
                        tool_calls += 1
                        trace.append(_trace_entry(rounds, call, result))
                        conversation.append(result.as_message())
                        continue

                    unknown = dispatch_tool(self._session, call)
                    trace.append(_trace_entry(rounds, call, unknown))
                    conversation.append(unknown.as_message())

                if submitted is not None:
                    return _finish_submit(
                        submitted,
                        reason=TerminationReason.ANSWERED,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

                if tool_calls >= self._max_tool_calls or rounds >= self._max_rounds:
                    return self._forced_submit(
                        conversation,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

        except Exception as exc:
            return AgentAnswer(
                text=(
                    "The agent stopped due to a provider or runtime error before a "
                    f"final answer could be submitted ({type(exc).__name__}: {exc})."
                ),
                citations=(),
                dropped_citation_ids=(),
                termination_reason=TerminationReason.ERROR,
                rounds=rounds,
                tool_calls=tool_calls,
                tool_trace=tuple(trace),
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _forced_submit(
        self,
        conversation: list[Message],
        *,
        rounds: int,
        tool_calls: int,
        trace: list[ToolTraceEntry],
    ) -> AgentAnswer:
        """One final `submit_answer`-only turn after budget exhaustion."""

        conversation.append(
            Message(role=MessageRole.USER, content=BUDGET_EXHAUSTED_USER_MESSAGE)
        )
        try:
            response = self._model.complete(
                conversation,
                (SUBMIT_ANSWER_TOOL,),
                policy=TurnPolicy(
                    tool_choice=ToolChoiceMode.REQUIRED,
                    tool_name=SUBMIT_ANSWER,
                ),
            )
            rounds += 1
        except Exception as exc:
            return AgentAnswer(
                text=(
                    "Tool budget was exhausted and the forced submit turn failed "
                    f"({type(exc).__name__}: {exc})."
                ),
                citations=(),
                dropped_citation_ids=(),
                termination_reason=TerminationReason.ERROR,
                rounds=rounds,
                tool_calls=tool_calls,
                tool_trace=tuple(trace),
            )

        _append_assistant(conversation, response)
        for call in response.tool_calls:
            if call.name != SUBMIT_ANSWER:
                continue
            result = dispatch_tool(self._session, call)
            trace.append(_trace_entry(rounds, call, result))
            conversation.append(result.as_message())
            if result.terminal and result.submitted is not None:
                return _finish_submit(
                    result.submitted,
                    reason=TerminationReason.BUDGET_EXHAUSTED,
                    rounds=rounds,
                    tool_calls=tool_calls,
                    trace=trace,
                )

        return AgentAnswer(
            text=(
                "Tool budget was exhausted and the model did not call submit_answer "
                "with a usable answer."
            ),
            citations=(),
            dropped_citation_ids=(),
            termination_reason=TerminationReason.ERROR,
            rounds=rounds,
            tool_calls=tool_calls,
            tool_trace=tuple(trace),
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedAgentError()


# === Helpers ===

def _append_assistant(conversation: list[Message], response: ModelResponse) -> None:
    conversation.append(
        Message(
            role=MessageRole.ASSISTANT,
            content=response.prose,
            tool_calls=response.tool_calls,
        )
    )

def _budget_skip(call: ToolCall) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        data={
            "ok": False,
            "error": "BudgetExhausted",
            "detail": "procurement tool-call budget exhausted",
        },
    )

def _trace_entry(round_no: int, call: ToolCall, result: ToolResult) -> ToolTraceEntry:
    return ToolTraceEntry(
        round=round_no,
        name=call.name,
        arguments=dict(call.arguments),
        ok=result.ok,
        observation=dict(result.data),
    )

def _finish_submit(
    submitted: SubmittedAnswer,
    *,
    reason: TerminationReason,
    rounds: int,
    tool_calls: int,
    trace: list[ToolTraceEntry],
) -> AgentAnswer:
    return AgentAnswer(
        text=submitted.answer,
        citations=submitted.citations,
        dropped_citation_ids=submitted.dropped_citation_ids,
        termination_reason=reason,
        rounds=rounds,
        tool_calls=tool_calls,
        tool_trace=tuple(trace),
    )
