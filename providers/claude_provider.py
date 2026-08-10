"""Claude provider — stub.

Exists so ProviderFactory can select AI_PROVIDER=claude without a
NameError, and so the unimplemented state is explicit
(NotImplementedError) rather than a silent no-op.
"""

from typing import Optional

import config
from providers.ai_provider import AIProvider


class ClaudeProvider(AIProvider):
    """Stub AIProvider for Claude — not yet implemented."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self._api_key = api_key if api_key is not None else config.CLAUDE_API_KEY
        self._model = model if model is not None else config.CLAUDE_MODEL

    @property
    def name(self) -> str:
        return "claude"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError("ClaudeProvider is not implemented yet")
