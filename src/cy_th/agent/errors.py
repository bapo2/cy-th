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

class InvalidModelRequestError(AgentError):
    """Raised for invalid conversation / policy inputs to `complete`."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# === Optional Provider Deps ===

class MissingOpenAIDepsError(AgentError):
    """Raised when the OpenAI adapter is used without `cy-th[openai]`."""

    def __init__(self, detail: str | None = None) -> None:
        hint = "install with: uv sync --extra openai  (or pip install 'cy-th[openai]')"
        msg = detail if detail is not None else "openai is not installed"
        super().__init__(f"{msg}; {hint}")
        self.detail = detail

class MissingModelKeyError(AgentError):
    """Raised when no API key is available for a provider adapter."""

    def __init__(self, *, env_var: str = "OPENAI_API_KEY") -> None:
        self.env_var = env_var
        super().__init__(f"missing API key; set {env_var} or pass api_key=...")
