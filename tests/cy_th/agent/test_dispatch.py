# tests/cy_th/agent/test_dispatch.py

"""Tool dispatch onto EvidenceSession (+ terminal submit_answer)."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from cy_th.agent.dispatch import dispatch_tool
from cy_th.agent.submit import SUBMIT_ANSWER
from cy_th.agent.tools import AGENT_TOOLS, EVIDENCE_TOOLS
from cy_th.agent.types import ToolCall
from cy_th.evidence.session import EvidenceSession


# === Catalog ===

def test_tool_definitions_helpers() -> None:
    assert "resolve_awards" in EVIDENCE_TOOLS
    assert EVIDENCE_TOOLS.get("missing") is None
    assert EVIDENCE_TOOLS.require("resolve_awards").name == "resolve_awards"
    with pytest.raises(KeyError):
        EVIDENCE_TOOLS.require("missing")
    assert len(tuple(EVIDENCE_TOOLS)) == len(EVIDENCE_TOOLS)
    assert "submit_answer" in AGENT_TOOLS.names


# === Evidence ===

def test_dispatch_resolve_and_award_evidence(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        resolved = dispatch_tool(
            ev,
            ToolCall(
                id="c1",
                name="resolve_awards",
                arguments={"filters": {"award_ids": ["A1"]}},
            ),
        )
        assert resolved.ok
        assert resolved.data["result"]["count"] == 1
        sel = resolved.data["result"]["selection"]["id"]

        cards = dispatch_tool(
            ev,
            ToolCall(
                id="c2",
                name="get_award_evidence",
                arguments={"selection": sel, "limit": 5},
            ),
        )
        assert cards.ok
        assert cards.data["result"]["cards"][0]["award_id"] == "A1"

def test_dispatch_aggregate_and_traverse(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        resolved = dispatch_tool(
            ev,
            ToolCall(
                id="c1",
                name="resolve_awards",
                arguments={"filters": {"award_ids": ["A1", "A2"]}},
            ),
        )
        sel = resolved.data["result"]["selection"]["id"]
        agg = dispatch_tool(
            ev,
            ToolCall(
                id="c2",
                name="aggregate_activity",
                arguments={
                    "selection": sel,
                    "window": {"from_date": "2025-01-01", "to_date": "2025-12-31"},
                    "group_by": "recipient",
                    "limit": 5,
                },
            ),
        )
        assert agg.ok
        assert agg.data["result"]["group_by"] == "recipient"

        trav = dispatch_tool(
            ev,
            ToolCall(
                id="c3",
                name="traverse_relationships",
                arguments={"selection": sel, "include": ["recipient"], "limit": 10},
            ),
        )
        assert trav.ok
        assert trav.data["result"]["truncated"] is False

def test_dispatch_unknown_tool(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        result = dispatch_tool(
            ev,
            ToolCall(id="c1", name="not_a_tool", arguments={}),
        )
        assert result.ok is False
        assert result.data["error"] == "UnknownTool"
        assert result.terminal is False

def test_dispatch_invalid_evidence_args(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        result = dispatch_tool(
            ev,
            ToolCall(id="c1", name="get_award_evidence", arguments={}),
        )
        assert result.ok is False
        assert "exactly one" in result.data["detail"]


# === Submit ===

def test_dispatch_submit_answer_terminal(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        dispatch_tool(
            ev,
            ToolCall(
                id="c0",
                name="get_award_evidence",
                arguments={"award_ids": ["A1"]},
            ),
        )
        result = dispatch_tool(
            ev,
            ToolCall(
                id="c1",
                name=SUBMIT_ANSWER,
                arguments={
                    "answer": "A1 belongs to Alpha.",
                    "citation_award_ids": ["A1", "HALLUC"],
                },
            ),
        )
        assert result.ok and result.terminal
        assert result.submitted is not None
        assert [c.award_id for c in result.submitted.citations] == ["A1"]
        assert result.submitted.dropped_citation_ids == ("HALLUC",)
        assert result.data["status"] == "submitted"
        msg = result.as_message()
        assert msg.tool_call_id == "c1"
        assert msg.name == SUBMIT_ANSWER

def test_dispatch_submit_answer_bad_args(agent_root: Path) -> None:
    with EvidenceSession.open(agent_root) as ev:
        result = dispatch_tool(
            ev,
            ToolCall(
                id="c1",
                name=SUBMIT_ANSWER,
                arguments={"answer": "", "citation_award_ids": []},
            ),
        )
        assert result.ok is False
        assert result.terminal is False
        assert result.data["error"] == "InvalidModelRequestError"
