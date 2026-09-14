# cy_th/agent/agent.py

"""Bounded procurement agent loop over `EvidenceSession` + `ModelClient`."""

# === Imports ===

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Self

from cy_th.agent.errors import ClosedAgentError, InvalidAgentRequestError
from cy_th.agent.prompts import (
    BUDGET_EXHAUSTED_USER_MESSAGE,
    NO_TOOL_CALL_USER_MESSAGE,
    SYSTEM_PROMPT,
)
from cy_th.agent.provider import (
    ModelClient,
    ModelRequest,
    OpenAIResponsesClient,
    ToolCall,
    ToolChoice,
    ToolChoiceMode,
    ToolResult,
)
from cy_th.agent.tools import (
    PROCUREMENT_TOOL_NAMES,
    SUBMIT_ANSWER,
    DispatchResult,
    dispatch_tool,
    tool_definitions,
)
from cy_th.agent.types import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_TOOL_CALLS,
    HARD_MAX_ROUNDS,
    HARD_MAX_TOOL_CALLS,
    AgentAnswer,
    TerminationReason,
    ToolTraceEntry,
    clamp_budget,
    filter_citations,
)
from cy_th.evidence.session import EvidenceSession


# === Agent ===

@dataclass(slots=True)
class ProcurementAgent:
    """Question-scoped agent that acquires evidence via tools then submits an answer.

    Evidence context reaches the model through tool observations (and provider conversation chaining). Standing prompt text lives in `prompts.py`.
    """

    _session: EvidenceSession
    _model: ModelClient
    _max_rounds: int = DEFAULT_MAX_ROUNDS
    _max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    _closed: bool = False
    _instructions: str = field(default=SYSTEM_PROMPT, repr=False)

    @classmethod
    def open(
        cls,
        data_root: Path | str | None = None,
        *,
        model_client: ModelClient | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
        instructions: str | None = None,
    ) -> Self:
        """Open an evidence session and bind a model client.

        When `model_client` is omitted, constructs `OpenAIResponsesClient.from_env()`.
        """

        try:
            rounds = clamp_budget(max_rounds, hard_max=HARD_MAX_ROUNDS, name="max_rounds")
            tools = clamp_budget(
                max_tool_calls, hard_max=HARD_MAX_TOOL_CALLS, name="max_tool_calls"
            )
        except ValueError as exc:
            raise InvalidAgentRequestError(str(exc)) from exc

        session = EvidenceSession.open(data_root)
        client: ModelClient = (
            # TODO: Remove this default fallback once we extend the model client protocol
            model_client if model_client is not None else OpenAIResponsesClient.from_env()
        )
        return cls(
            _session=session,
            _model=client,
            _max_rounds=rounds,
            _max_tool_calls=tools,
            _instructions=SYSTEM_PROMPT if instructions is None else instructions,
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

        rounds = 0
        tool_calls = 0
        trace: list[ToolTraceEntry] = []
        previous_response_id: str | None = None
        pending_results: tuple[ToolResult, ...] = ()
        input_text: str | None = text

        try:
            while True:
                if rounds >= self._max_rounds or tool_calls >= self._max_tool_calls:
                    return self._forced_submit(
                        previous_response_id=previous_response_id,
                        pending_results=pending_results,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

                response = self._model.complete(
                    ModelRequest(
                        instructions=self._instructions,
                        tools=tool_definitions(
                            include_procurement=True, include_submit=True
                        ),
                        tool_choice=ToolChoice(mode=ToolChoiceMode.AUTO),
                        input_text=input_text,
                        previous_response_id=previous_response_id,
                        tool_results=pending_results,
                    )
                )
                rounds += 1
                previous_response_id = response.response_id or previous_response_id
                input_text = None
                pending_results = ()

                if not response.tool_calls:
                    # Prose-only is not a valid terminal act (nudge and continue)
                    if rounds >= self._max_rounds or tool_calls >= self._max_tool_calls:
                        return self._forced_submit(
                            previous_response_id=previous_response_id,
                            pending_results=(),
                            rounds=rounds,
                            tool_calls=tool_calls,
                            trace=trace,
                        )
                    input_text = NO_TOOL_CALL_USER_MESSAGE
                    continue

                results: list[ToolResult] = []
                submitted: DispatchResult | None = None

                for call in response.tool_calls:
                    if call.name == SUBMIT_ANSWER:
                        dispatched = dispatch_tool(
                            self._session, call.name, call.arguments
                        )
                        trace.append(_trace_entry(rounds, call, dispatched))
                        results.append(
                            ToolResult(call_id=call.call_id, output=dict(dispatched.observation))
                        )
                        if dispatched.ok and dispatched.submit is not None:
                            submitted = dispatched
                            break
                        continue

                    if call.name in PROCUREMENT_TOOL_NAMES:
                        if tool_calls >= self._max_tool_calls:
                            # Budget hit mid-turn, skip further procurement calls
                            skipped = DispatchResult(
                                name=call.name,
                                arguments=dict(call.arguments),
                                ok=False,
                                observation={
                                    "error": "BudgetExhausted",
                                    "detail": "procurement tool-call budget exhausted",
                                },
                            )
                            trace.append(_trace_entry(rounds, call, skipped))
                            results.append(
                                ToolResult(
                                    call_id=call.call_id,
                                    output=dict(skipped.observation),
                                )
                            )
                            continue

                        dispatched = dispatch_tool(
                            self._session, call.name, call.arguments
                        )
                        tool_calls += 1
                        trace.append(_trace_entry(rounds, call, dispatched))
                        results.append(
                            ToolResult(
                                call_id=call.call_id,
                                output=dict(dispatched.observation),
                            )
                        )
                        continue

                    # Unknown tool name
                    unknown = dispatch_tool(self._session, call.name, call.arguments)
                    trace.append(_trace_entry(rounds, call, unknown))
                    results.append(
                        ToolResult(call_id=call.call_id, output=dict(unknown.observation))
                    )

                if submitted is not None and submitted.submit is not None:
                    return self._finish_submit(
                        submitted,
                        reason=TerminationReason.ANSWERED,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

                pending_results = tuple(results)
                if tool_calls >= self._max_tool_calls or rounds >= self._max_rounds:
                    return self._forced_submit(
                        previous_response_id=previous_response_id,
                        pending_results=pending_results,
                        rounds=rounds,
                        tool_calls=tool_calls,
                        trace=trace,
                    )

        except Exception as exc:
            return AgentAnswer(
                text=(
                    f"The agent stopped due to a provider or runtime error before a final answer could be submitted ({type(exc).__name__}: {exc})."
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
        *,
        previous_response_id: str | None,
        pending_results: tuple[ToolResult, ...],
        rounds: int,
        tool_calls: int,
        trace: list[ToolTraceEntry],
    ) -> AgentAnswer:
        """One final submit_answer-only turn after budget exhaustion."""

        try:
            response = self._model.complete(
                ModelRequest(
                    instructions=self._instructions,
                    tools=tool_definitions(
                        include_procurement=False, include_submit=True
                    ),
                    tool_choice=ToolChoice(
                        mode=ToolChoiceMode.REQUIRED,
                        tool_name=SUBMIT_ANSWER,
                    ),
                    input_text=BUDGET_EXHAUSTED_USER_MESSAGE,
                    previous_response_id=previous_response_id,
                    tool_results=pending_results,
                )
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

        for call in response.tool_calls:
            if call.name != SUBMIT_ANSWER:
                continue
            dispatched = dispatch_tool(self._session, call.name, call.arguments)
            trace.append(_trace_entry(rounds, call, dispatched))
            if dispatched.ok and dispatched.submit is not None:
                return self._finish_submit(
                    dispatched,
                    reason=TerminationReason.BUDGET_EXHAUSTED,
                    rounds=rounds,
                    tool_calls=tool_calls,
                    trace=trace,
                )

        return AgentAnswer(
            text=(
                "Tool budget was exhausted and the model did not call submit_answer with a usable answer."
            ),
            citations=(),
            dropped_citation_ids=(),
            termination_reason=TerminationReason.ERROR,
            rounds=rounds,
            tool_calls=tool_calls,
            tool_trace=tuple(trace),
        )

    def _finish_submit(
        self,
        dispatched: DispatchResult,
        *,
        reason: TerminationReason,
        rounds: int,
        tool_calls: int,
        trace: list[ToolTraceEntry],
    ) -> AgentAnswer:
        assert dispatched.submit is not None
        filtered = filter_citations(
            dispatched.submit.citation_award_ids,
            self._session.acquired_award_cards(),
        )
        return AgentAnswer(
            text=dispatched.submit.answer,
            citations=filtered.citations,
            dropped_citation_ids=filtered.dropped_citation_ids,
            termination_reason=reason,
            rounds=rounds,
            tool_calls=tool_calls,
            tool_trace=tuple(trace),
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedAgentError()


# === Helpers ===

def _trace_entry(
    round_no: int,
    call: ToolCall,
    dispatched: DispatchResult,
) -> ToolTraceEntry:
    return ToolTraceEntry(
        round=round_no,
        name=call.name,
        arguments=dict(call.arguments),
        ok=dispatched.ok,
        observation=dict(dispatched.observation),
    )
