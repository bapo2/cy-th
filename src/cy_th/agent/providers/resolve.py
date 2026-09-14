# cy_th/agent/providers/resolve.py

"""Resolve a provider name into a concrete `ModelSession`.

CLI / library callers pick a provider string; this module owns the registry so new adapters register in one place. Default provider is OpenAI.
"""

# === Imports ===

from __future__ import annotations
from typing import Final
import os

from cy_th.agent.errors import InvalidAgentRequestError
from cy_th.agent.protocol import ModelSession


# === Constants ===

DEFAULT_PROVIDER: Final[str] = "openai"
ENV_PROVIDER: Final[str] = "CYTH_PROVIDER"

_KNOWN: Final[tuple[str, ...]] = ("openai",)


# === Resolve ===

def open_model_session(
    provider: str | None = None,
    *,
    instructions: str | None = None,
    model: str | None = None,
) -> ModelSession:
    """Construct a `ModelSession` for `provider` (default: OpenAI / `CYTH_PROVIDER`).

    #### Args:
        - `provider`: Adapter name (`openai` by-default currently). When `None`, uses `CYTH_PROVIDER` or `openai`
        - `instructions`: Standing system / instructions text for the session
        - `model`: Optional provider model id (else adapter env / default)
    """

    name = _normalize_provider(provider)
    if name == "openai":
        from cy_th.agent.providers.openai import OpenAIModelSession

        return OpenAIModelSession(model=model, instructions=instructions)

    known = ", ".join(_KNOWN)
    raise InvalidAgentRequestError(
        f"unknown model provider {name!r}; known providers: {known}"
    )

def known_providers() -> tuple[str, ...]:
    """Registered live provider names (excludes test-only fakes)."""

    return _KNOWN


# === Helpers ===

def _normalize_provider(provider: str | None) -> str:
    if provider is not None:
        text = provider.strip().lower()
        if text:
            return text
    env = os.environ.get(ENV_PROVIDER, "").strip().lower()
    if env:
        return env
    return DEFAULT_PROVIDER
