# cy_th/agent/errors.py

"""Errors raised by the procurement agent layer."""

# === Imports ===

from __future__ import annotations


# === Base ===

class AgentError(RuntimeError):
    """Base class for procurement-agent failures."""


# === Lifecycle / Requests ===

class ClosedAgentError(AgentError):
    """Raised when using a closed `ProcurementAgent`."""

    def __init__(self, detail: str = "ProcurementAgent is closed") -> None:
        self.detail = detail
        super().__init__(detail)

class InvalidAgentRequestError(AgentError):
    """Raised for invalid agent arguments (budgets, blank questions, etc.)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

class MissingModelKeyError(AgentError):
    """Raised when constructing the model client without a set key.
    
    Currently just flags missing OpenAI API key.
    """

    def __init__(self, detail: str = "OPENAI_API_KEY is not set") -> None:
        self.detail = detail
        super().__init__(detail)
