"""Ollama HTTP API provider.

Talks to a local Ollama server over its HTTP API only — never the
`ollama` CLI. Stateless: every generate() call is a fully independent
HTTP request; no prompt, model, or conversation state is retained
between calls, and instances are safe to reuse across calls/threads.
"""

import logging
from typing import Any, Dict, Optional

import requests

import config
from providers.ai_provider import AIProvider

logger = logging.getLogger(__name__)

_CHAT_ENDPOINT = "/api/chat"
_DEFAULT_TIMEOUT_SECONDS = 120


class OllamaProviderError(Exception):
    """Raised when the Ollama HTTP API cannot be reached or returns an unusable response."""


class OllamaProvider(AIProvider):
    """AIProvider implementation backed by the Ollama HTTP API.

    Holds only connection/generation configuration (base URL, model,
    temperature, context window, keep-alive) — never prompt or
    conversation state. Each generate() call is fully independent.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        keep_alive: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # Reads config.* at call time (not import time) so a runtime
        # config change (e.g. via the Settings dialog) takes effect on
        # the next provider construction without an app restart.
        self._base_url = (base_url if base_url is not None else config.OLLAMA_URL).rstrip("/")
        self._model = model if model is not None else config.OLLAMA_MODEL
        self._temperature = temperature if temperature is not None else config.OLLAMA_TEMPERATURE
        self._num_ctx = num_ctx if num_ctx is not None else config.OLLAMA_NUM_CTX
        self._keep_alive = keep_alive if keep_alive is not None else config.OLLAMA_KEEP_ALIVE
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:

        logger.info("Calling Ollama model '%s' at %s", self._model, self._base_url)

        try:
            response = requests.post(
                f"{self._base_url}{_CHAT_ENDPOINT}",
                json=self._build_request_body(system_prompt, user_prompt),
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaProviderError(f"Ollama request failed: {exc}") from exc

        return self._extract_content(response)

    def _build_request_body(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:

        return {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
            "keep_alive": self._keep_alive,
        }

    @staticmethod
    def _extract_content(response: requests.Response) -> str:

        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaProviderError(f"Ollama response was not valid JSON: {exc}") from exc

        try:
            return payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaProviderError(f"Unexpected Ollama response shape: {payload}") from exc
