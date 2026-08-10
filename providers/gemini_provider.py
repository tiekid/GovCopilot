"""Google Gemini provider using the official google-genai SDK.

Talks to Gemini via the current, actively-maintained `google-genai`
SDK. (The older `google-generativeai` package was evaluated first but
is now deprecated by Google — "All support ... has ended" — so this
uses the SDK Google actually recommends today.) Stateless: every
generate() call builds a fresh client/request; no prompt or
conversation state is retained between calls.

No Gemini model name is ever hardcoded. If none is configured,
generate() discovers the first available model that supports text
generation on first use and persists it (see _discover_and_store_model
/ config_store.set_config_value). If the configured model has since
been retired (the API returns 404 NOT_FOUND), generate() automatically
selects a replacement (see _select_replacement_model) and retries once
— a stale model name self-heals instead of failing the whole
extraction. The replacement is ranked (gemini-flash-latest >
gemini-2.5-flash-lite > gemini-2.0-flash > any remaining flash model)
against whatever client.models.list() actually returns — a preferred
name is never assumed to exist without checking — and is restricted to
flash-tier models only: pro-tier models are never selected
automatically (confirmed zero free-tier quota in production; see
docs/09_LESSONS_LEARNED.md). The model that just failed is always
excluded, since Gemini's models.list() can still list a model that
404s for a specific key/account — e.g. "no longer available to new
users" — so re-discovery without excluding it could pick the same
broken model again.
"""

import logging
from typing import Any, Iterable, List, Optional, Tuple

from google import genai
from google.genai import errors, types

import config
from config_store import set_config_value
from providers.ai_provider import AIProvider, ProviderConfigurationError

logger = logging.getLogger(__name__)

# Extraction is a determinism task, not creative generation — mirrors
# OllamaProvider's OLLAMA_TEMPERATURE=0 default.
_GEMINI_TEMPERATURE = 0

# The action name the Gemini API uses to mark a model as capable of
# text generation (as opposed to e.g. embeddings-only models).
_TEXT_GENERATION_ACTION = "generateContent"

_MODEL_NAME_PREFIX = "models/"


class GeminiProviderError(Exception):
    """Raised when the Gemini API request fails or returns an unusable response.

    Always the type callers see for a Gemini failure — a raw SDK/API
    exception never escapes this module.
    """


def list_text_generation_models(api_key: str) -> List[str]:
    """Return Gemini model names that support text generation, in API-listed order."""

    if not api_key:
        raise ProviderConfigurationError("Gemini API key is not configured.")

    try:
        client = genai.Client(api_key=api_key)

        return [
            _strip_model_prefix(model.name)
            for model in client.models.list()
            if _TEXT_GENERATION_ACTION in (getattr(model, "supported_actions", None) or [])
        ]

    except Exception as exc:
        raise GeminiProviderError(f"Failed to list Gemini models: {exc}") from exc


def select_first_text_generation_model(
    api_key: str, exclude: Optional[Iterable[str]] = None
) -> str:
    """Return the first available Gemini model that supports text generation.

    `exclude` matters in practice, not just in theory: the Gemini API
    can list a model (models.list() includes it, generateContent is in
    its supported_actions) that still 404s NOT_FOUND for a specific key
    — e.g. "no longer available to new users" — so re-discovering after
    a 404 without excluding the model that just failed can pick the
    exact same broken model again.
    """

    excluded = set(exclude or ())
    models = [name for name in list_text_generation_models(api_key) if name not in excluded]

    if not models:
        raise GeminiProviderError("No Gemini model supporting text generation is available")

    return models[0]


def _strip_model_prefix(name: str) -> str:
    return name[len(_MODEL_NAME_PREFIX):] if name.startswith(_MODEL_NAME_PREFIX) else name


def _is_model_not_found(exc: errors.APIError) -> bool:
    return getattr(exc, "code", None) == 404 or getattr(exc, "status", None) == "NOT_FOUND"


# Ranking only — never assumed to exist. Every name here is checked
# against the real client.models.list() response before use; a name
# not actually present in that response is never selected. Pro-tier
# models are never candidates for automatic replacement: real testing
# showed zero free-tier quota on gemini-2.5-pro (see
# docs/09_LESSONS_LEARNED.md), so a 404 must never auto-switch to a
# pro model.
_PREFERRED_REPLACEMENT_MODELS: Tuple[str, ...] = (
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
)


def _select_replacement_model(api_key: str, exclude: str) -> Tuple[str, str]:
    """Select a replacement for `exclude` (which just 404'd), and why it was chosen.

    Restricted to flash-tier models only (name contains "flash", not
    "pro") — pro-tier models are never selected automatically. Ranked
    by _PREFERRED_REPLACEMENT_MODELS; the first preferred name actually
    present in the live model list wins. If none of the preferred names
    are available, the first remaining flash model in API-listed order
    is used. Raises GeminiProviderError if no flash model remains.
    """

    candidates = [
        name
        for name in list_text_generation_models(api_key)
        if name != exclude and "flash" in name and "pro" not in name
    ]

    if not candidates:
        raise GeminiProviderError(
            f"No compatible replacement model available after excluding '{exclude}' "
            "(no remaining flash-tier model supports text generation)"
        )

    for preferred in _PREFERRED_REPLACEMENT_MODELS:
        if preferred in candidates:
            return preferred, f"preferred replacement '{preferred}' is available"

    fallback = candidates[0]
    return fallback, f"no preferred replacement available; using first remaining flash model '{fallback}'"


class GeminiProvider(AIProvider):
    """AIProvider implementation backed by the official google-genai SDK.

    Missing configuration (no API key) raises ProviderConfigurationError
    immediately, at construction time — before any SDK call is ever
    attempted — so a missing key is a clear, catchable configuration
    error, never a raw SDK exception surfacing to the caller.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:

        # Reads config.* at call time (not import time) so a runtime
        # config change (e.g. via the Settings dialog) takes effect on
        # the next provider construction without an app restart.
        resolved_api_key = api_key if api_key is not None else config.GEMINI_API_KEY

        if not resolved_api_key:
            raise ProviderConfigurationError("Gemini API key is not configured.")

        self._api_key = resolved_api_key
        self._model = model if model is not None else config.GEMINI_MODEL

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:

        if not self._model:
            self._model = self._discover_and_store_model()

        try:
            return self._call_gemini(self._model, system_prompt, user_prompt)

        except GeminiProviderError:
            raise

        except errors.APIError as exc:
            if not _is_model_not_found(exc):
                raise GeminiProviderError(f"Gemini request failed: {exc}") from exc

            return self._retry_with_replacement_model(system_prompt, user_prompt, exc)

        except Exception as exc:
            raise GeminiProviderError(f"Gemini request failed: {exc}") from exc

    def _retry_with_replacement_model(
        self, system_prompt: str, user_prompt: str, original_exc: errors.APIError
    ) -> str:

        previous_model = self._model

        try:
            replacement, reason = _select_replacement_model(self._api_key, exclude=previous_model)
        except GeminiProviderError as discovery_exc:
            logger.warning(
                "Configured model: '%s' -> Failed (404 NOT_FOUND) -> No replacement available -> %s",
                previous_model,
                discovery_exc,
            )
            raise GeminiProviderError(
                f"Gemini model '{previous_model}' not found, and no replacement "
                f"could be selected: {discovery_exc}"
            ) from original_exc

        logger.warning(
            "Configured model: '%s' -> Failed (404 NOT_FOUND) -> Selected replacement: '%s' -> Reason: %s",
            previous_model,
            replacement,
            reason,
        )

        try:
            result = self._call_gemini(replacement, system_prompt, user_prompt)
        except Exception as retry_exc:
            raise GeminiProviderError(
                f"Gemini request failed even after switching to model '{replacement}': {retry_exc}"
            ) from retry_exc

        # Cache the confirmed-working model on the instance and persist
        # it, so this instance's next call — and every future
        # GeminiProvider construction — skips straight to a model
        # already known to work, instead of re-discovering from scratch.
        self._model = replacement
        set_config_value("GEMINI_MODEL", replacement)

        return result

    def _call_gemini(self, model: str, system_prompt: str, user_prompt: str) -> str:

        logger.info("Calling Gemini model '%s'", model)

        client = genai.Client(api_key=self._api_key)

        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=_GEMINI_TEMPERATURE,
            ),
        )

        return self._extract_text(response)

    def _discover_and_store_model(self, exclude: Optional[Iterable[str]] = None) -> str:

        model = select_first_text_generation_model(self._api_key, exclude=exclude)

        set_config_value("GEMINI_MODEL", model)

        logger.info("Selected Gemini model: %s", model)

        return model

    @staticmethod
    def _extract_text(response: Any) -> str:

        text = getattr(response, "text", None)

        if not text:
            raise GeminiProviderError("Gemini response contained no text")

        return text
