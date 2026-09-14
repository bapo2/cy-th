# tests/cy_th/agent/test_agent.py

"""Bounded ProcurementAgent loop (FakeModelSession, offline)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.agent.agent import HARD_MAX_ROUNDS, ProcurementAgent, clamp_budget
from cy_th.agent.errors import ClosedAgentError, InvalidAgentRequestError
from cy_th.agent.providers.fake import FakeModelSession
from cy_th.agent.submit import SUBMIT_ANSWER, TerminationReason
from cy_th.agent.types import ModelResponse, ToolCall, ToolChoiceMode


# === Helpers ===

def _submit(answer: str, *award_ids: str) -> ModelResponse:
    return ModelResponse(
        prose=None,
        tool_calls=(
            ToolCall(
                id="submit",
                name=SUBMIT_ANSWER,
                arguments={
                    "answer": answer,
                    "citation_award_ids": list(award_ids),
                },
            ),
        ),
    )

def _evidence(award_id: str = "A1") -> ModelResponse:
    return ModelResponse(
        prose=None,
        tool_calls=(
            ToolCall(
                id="ev",
                name="get_award_evidence",
                arguments={"award_ids": [award_id]},
            ),
        ),
    )


# === Budgets ===

def test_clamp_budget_rejects_nonpositive() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        clamp_budget(0, hard_max=HARD_MAX_ROUNDS, name="max_rounds")

def test_open_clamps_budget(agent_root: Path) -> None:
    fake = FakeModelSession([_submit("done")])
    with ProcurementAgent.open(
        agent_root,
        model_session=fake,
        max_rounds=99,
        max_tool_calls=99,
    ) as agent:
        assert agent.max_rounds == HARD_MAX_ROUNDS
        assert agent.max_tool_calls == 24


# === Answered ===

def test_answer_multi_round_with_citation_filter(agent_root: Path) -> None:
    fake = FakeModelSession(
        [
            _evidence("A1"),
            _submit("Award A1 went to Alpha Corp.", "A1", "HALLUCINATED", "A1"),
        ]
    )
    with ProcurementAgent.open(agent_root, model_session=fake) as agent:
        answer = agent.answer("Who got A1?")

    assert answer.termination_reason is TerminationReason.ANSWERED
    assert "Alpha" in answer.text or "A1" in answer.text
    assert [c.award_id for c in answer.citations] == ["A1"]
    assert answer.dropped_citation_ids == ("HALLUCINATED",)
    assert answer.rounds == 2
    assert answer.tool_calls == 1
    assert [e.name for e in answer.tool_trace] == [
        "get_award_evidence",
        "submit_answer",
    ]

def test_answer_no_evidence_submit_allowed(agent_root: Path) -> None:
    fake = FakeModelSession([_submit("Insufficient evidence in this set.", )])
    with ProcurementAgent.open(agent_root, model_session=fake) as agent:
        answer = agent.answer("Anything about Z9?")

    assert answer.termination_reason is TerminationReason.ANSWERED
    assert answer.citations == ()
    assert answer.dropped_citation_ids == ()
    assert answer.tool_calls == 0


# === Budget ===

def test_budget_exhaustion_forces_submit(agent_root: Path) -> None:
    def forced_turn(conversation, tools, policy):  # type: ignore[no-untyped-def]
        assert len(tools) == 1
        assert tools[0].name == SUBMIT_ANSWER
        assert policy.tool_choice is ToolChoiceMode.REQUIRED
        assert policy.tool_name == SUBMIT_ANSWER
        assert any(
            m.content and "budget exhausted" in m.content.lower()
            for m in conversation
            if m.content
        )
        return _submit("Forced wrap-up on A1.", "A1")

    fake = FakeModelSession(
        [
            _evidence("A1"),
            forced_turn,
        ]
    )
    with ProcurementAgent.open(
        agent_root,
        model_session=fake,
        max_rounds=1,
        max_tool_calls=12,
    ) as agent:
        answer = agent.answer("Tell me about A1")

    assert answer.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert [c.award_id for c in answer.citations] == ["A1"]
    assert answer.rounds == 2  # one normal + forced submit turn
    assert answer.tool_calls == 1


# === Errors / Lifecycle ===

def test_blank_question_rejected(agent_root: Path) -> None:
    fake = FakeModelSession([_submit("unused")])
    with ProcurementAgent.open(agent_root, model_session=fake) as agent:
        with pytest.raises(InvalidAgentRequestError, match="non-empty"):
            agent.answer("   ")

def test_closed_agent_rejects_answer(agent_root: Path) -> None:
    fake = FakeModelSession([_submit("unused")])
    agent = ProcurementAgent.open(agent_root, model_session=fake)
    agent.close()
    with pytest.raises(ClosedAgentError):
        agent.answer("Who got A1?")

def test_provider_error_terminates_with_error(agent_root: Path) -> None:
    def boom(conversation, tools, policy):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider down")

    fake = FakeModelSession([boom])
    with ProcurementAgent.open(agent_root, model_session=fake) as agent:
        answer = agent.answer("Who got A1?")

    assert answer.termination_reason is TerminationReason.ERROR
    assert "RuntimeError" in answer.text
    assert answer.citations == ()
