# cy_th/agent/errors.py

"""Errors raised by model sessions and agent orchestration."""

# === Imports ===

from __future__ import annotations


# === Base ===

class AgentError(RuntimeError):
    """Base class for agent / model-session failures."""


# === Session ===

class ClosedModelSessionError(AgentError):
    """Raised when using a closed `ModelSession`."""

    def __init__(self, detail: str = "ModelSession is closed") -> None:
        self.detail = detail
        super().__init__(detail)
