"""Abstraction over AI backends used by AI-driven agents.

Providers are pure transport: given a system prompt and a user prompt,
return the model's raw response text. They are stateless — no prompt,
model, conversation, or history is cached across calls — so a single
provider instance is interchangeable and safe to reuse across calls
and threads.

Providers know nothing about the caller's task (extraction, review,
proposal drafting, ...) or the shape of the response (JSON or
otherwise). That parsing and validation belongs to the caller.
"""

from typing import Protocol


class ProviderConfigurationError(Exception):
    """Raised when a provider is selected but not usably configured (e.g. missing API key).

    Provider-agnostic and shared across implementations so callers
    (AIInvitationExtractor, the UI) can distinguish "not configured yet"
    from a transient request failure without knowing which concrete
    provider is in use.
    """


class AIProvider(Protocol):
    """A stateless, single-turn completion backend."""

    @property
    def name(self) -> str:
        """Short provider identifier (e.g. "ollama", "gemini") — for logging only."""
        ...

    @property
    def model(self) -> str:
        """The specific model this provider is configured to use — for logging only."""
        ...

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return the raw model response text for one independent completion call.

        Each call is fully self-contained: no state from a previous
        call may influence this one.
        """
        ...
