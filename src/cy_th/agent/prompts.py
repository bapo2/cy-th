# cy_th/agent/prompts.py

"""Prompt text literals for the procurement agent (code-authoritative)."""

# === Imports ===

from __future__ import annotations


# === Prompts ===

SYSTEM_PROMPT: str = """\
TODO: Define the agent's standing instructions.
"""

# Mechanical nudge for the forced final turn (not a full prompt-engineering surface yet)
BUDGET_EXHAUSTED_USER_MESSAGE: str = (
    "[system] Tool budget exhausted. Call submit_answer now using only evidence already acquired; state uncertainty where needed."
)

# Mechanical nudge when the model returns no tool calls
NO_TOOL_CALL_USER_MESSAGE: str = (
    "[system] No tool call was returned. Call a procurement tool or submit_answer."
)
