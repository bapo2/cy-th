# tests/cy_th/agent/test_fake.py

"""Offline FakeModelSession behavior."""

# === Imports ===

from __future__ import annotations
import pytest

from cy_th.agent.errors import ClosedModelSessionError
from cy_th.agent.providers.fake import ExhaustedFakeResponsesError, FakeModelSession
from cy_th.agent.types import (
    Message,
    MessageRole,
    ModelResponse,
    ToolCall,
    ToolChoiceMode,
    TurnPolicy,
)


# === Scripting ===

def test_fake_returns_scripted_responses_in_order() -> None:
    session = FakeModelSession(
        [
            ModelResponse(prose="hi"),
            ModelResponse(
                prose=None,
                tool_calls=(
                    ToolCall(id="c1", name="resolve_awards", arguments={"filters": {}}),
                ),
            ),
        ]
    )
    conv = [Message(role=MessageRole.USER, content="q")]
    assert session.complete(conv).prose == "hi"
    second = session.complete(conv)
    assert second.tool_calls[0].name == "resolve_awards"
    assert len(session.calls) == 2
    with pytest.raises(ExhaustedFakeResponsesError):
        session.complete(conv)

def test_fake_responder_sees_policy_and_tools() -> None:
    seen: dict[str, object] = {}

    def responder(conversation, tools, policy):  # type: ignore[no-untyped-def]
        seen["n_tools"] = len(tools)
        seen["policy"] = policy
        return ModelResponse(prose="ok")

    session = FakeModelSession([responder])
    from cy_th.agent.tools import SUBMIT_ANSWER_TOOL

    session.complete(
        [Message(role=MessageRole.USER, content="q")],
        (SUBMIT_ANSWER_TOOL,),
        policy=TurnPolicy(
            tool_choice=ToolChoiceMode.REQUIRED,
            tool_name="submit_answer",
        ),
    )
    assert seen["n_tools"] == 1
    policy = seen["policy"]
    assert isinstance(policy, TurnPolicy)
    assert policy.tool_choice is ToolChoiceMode.REQUIRED
    assert policy.tool_name == "submit_answer"

def test_fake_close_blocks_complete() -> None:
    session = FakeModelSession([ModelResponse(prose="x")])
    session.close()
    with pytest.raises(ClosedModelSessionError):
        session.complete([Message(role=MessageRole.USER, content="q")])
