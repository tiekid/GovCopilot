"""Provider that tries a preferred provider first, falling back on failure.

Makes an optional, faster/better provider (e.g. Gemini) safe to prefer:
if it's unavailable — unreachable, out of quota, times out — the
application automatically continues with the fallback provider (e.g.
Ollama) instead of failing the whole extraction. Missing configuration
(e.g. no API key) is handled one level up, in ProviderFactory, which
never constructs a primary that can't be constructed in the first
place — see providers/provider_factory.py.

Stateless like any other AIProvider: each generate() call independently
tries primary then fallback; no state carries between calls.
"""

import logging
from typing import Tuple, Type

from providers.ai_provider import AIProvider

logger = logging.getLogger(__name__)


class FallbackProvider(AIProvider):
    """Tries `primary.generate()`; on a recognized primary failure, tries `fallback.generate()`.

    Only exception types the primary provider itself uses to signal
    "I could not serve this request" (`primary_error_types`) trigger the
    fallback — anything else propagates, so a bug is never mistaken for
    "provider unavailable" and silently masked.
    """

    def __init__(
        self,
        primary: AIProvider,
        fallback: AIProvider,
        primary_error_types: Tuple[Type[Exception], ...],
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_error_types = primary_error_types

    @property
    def name(self) -> str:
        return f"{self._primary.name}->{self._fallback.name}"

    @property
    def model(self) -> str:
        return self._primary.model

    def generate(self, system_prompt: str, user_prompt: str) -> str:

        try:
            return self._primary.generate(system_prompt, user_prompt)

        except self._primary_error_types as exc:
            logger.warning(
                "Primary provider '%s' unavailable (%s); falling back to '%s'",
                self._primary.name,
                exc,
                self._fallback.name,
            )
            return self._fallback.generate(system_prompt, user_prompt)
