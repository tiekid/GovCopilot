"""Selects and constructs the configured AIProvider implementation.

The only place in the codebase that knows about concrete provider
classes. AIInvitationExtractor — and everything above it
(MeetingParserAgent, ...) — depends only on the AIProvider Protocol
and never chooses an implementation itself.
"""

import logging
from typing import Callable, Dict, Optional

import config
from providers.ai_provider import AIProvider

logger = logging.getLogger(__name__)


class UnknownProviderError(Exception):
    """Raised when AI_PROVIDER names a provider ProviderFactory doesn't recognize."""


def _create_ollama_provider() -> AIProvider:
    from providers.ollama_provider import OllamaProvider

    return OllamaProvider()


def _create_gemini_provider() -> AIProvider:
    from providers.gemini_provider import GeminiProvider

    return GeminiProvider()


def _create_openai_provider() -> AIProvider:
    from providers.openai_provider import OpenAIProvider

    return OpenAIProvider()


def _create_claude_provider() -> AIProvider:
    from providers.claude_provider import ClaudeProvider

    return ClaudeProvider()


def _create_auto_provider() -> AIProvider:
    """Gemini preferred, Ollama as the automatic fallback.

    If Gemini isn't configured at all (no API key), there is nothing to
    fall back *from* — this returns a plain OllamaProvider directly,
    never a FallbackProvider wrapping a provider that can't exist. Once
    Gemini is configured, generate() calls try Gemini first and fall
    back to Ollama for any runtime failure (quota, timeout, network) —
    every such failure surfaces from GeminiProvider as GeminiProviderError.
    """
    from providers.ai_provider import ProviderConfigurationError
    from providers.fallback_provider import FallbackProvider
    from providers.gemini_provider import GeminiProvider, GeminiProviderError
    from providers.ollama_provider import OllamaProvider

    try:
        primary = GeminiProvider()
    except ProviderConfigurationError as exc:
        logger.info("Gemini not configured (%s); using Ollama directly", exc)
        return OllamaProvider()

    return FallbackProvider(
        primary=primary,
        fallback=OllamaProvider(),
        primary_error_types=(GeminiProviderError,),
    )


# Each factory imports its provider class lazily (inside the function),
# so selecting "ollama" never requires the Gemini/OpenAI/Claude SDKs (or
# their credentials) to be installed/configured, and vice versa.
_FACTORIES: Dict[str, Callable[[], AIProvider]] = {
    "ollama": _create_ollama_provider,
    "gemini": _create_gemini_provider,
    "openai": _create_openai_provider,
    "claude": _create_claude_provider,
    "auto": _create_auto_provider,
}


def create_provider(provider_name: Optional[str] = None) -> AIProvider:
    """Construct the AIProvider named by `provider_name`, or config.AI_PROVIDER if omitted.

    Reads config.AI_PROVIDER at call time (not import time), so a
    runtime config change (e.g. via the Settings dialog) is picked up
    on the very next call, without an app restart.
    """

    name = (provider_name or config.AI_PROVIDER or "").strip().lower()

    factory = _FACTORIES.get(name)

    if factory is None:
        raise UnknownProviderError(
            f"Unknown AI_PROVIDER '{name}'. Supported providers: {', '.join(sorted(_FACTORIES))}"
        )

    logger.info("Selected AI provider: %s", name)

    return factory()
