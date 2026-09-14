# cy_th/agent/prompts.py

"""Prompt / instruction literals for the procurement agent."""

# === Literals (stubs) ===

SYSTEM_PROMPT: str = """\
TODO: Define the agent's standing instructions.
"""

BUDGET_EXHAUSTED_USER_MESSAGE: str = (
    "[system] Tool budget exhausted. Call submit_answer now using only evidence already acquired; state uncertainty where needed."
)

NO_TOOL_CALL_USER_MESSAGE: str = (
    "[system] You must call a tool. Either acquire more evidence with a procurement tool or call submit_answer to finish."
)
