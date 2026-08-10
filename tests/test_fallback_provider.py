"""Unit tests for providers/fallback_provider.py and the "auto" ProviderFactory selection.

No real network access — Gemini and Ollama's transport layers are both
mocked where the real classes are exercised.
"""

import unittest
from unittest.mock import MagicMock, patch

import config
from providers.fallback_provider import FallbackProvider
from providers.provider_factory import create_provider


class _FakeProvider:
    """Minimal AIProvider double that can be made to fail on demand."""

    def __init__(self, name: str, model: str = "model", response=None, error: Exception = None) -> None:
        self._name = name
        self._model = model
        self._response = response
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._response


class FallbackProviderTests(unittest.TestCase):

    def test_uses_primary_result_when_primary_succeeds(self) -> None:
        primary = _FakeProvider("primary", response="from-primary")
        fallback = _FakeProvider("fallback", response="from-fallback")
        provider = FallbackProvider(primary, fallback, primary_error_types=(RuntimeError,))

        result = provider.generate("sys", "user")

        self.assertEqual(result, "from-primary")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)

    def test_falls_back_when_primary_raises_recognized_error(self) -> None:
        primary = _FakeProvider("primary", error=RuntimeError("boom"))
        fallback = _FakeProvider("fallback", response="from-fallback")
        provider = FallbackProvider(primary, fallback, primary_error_types=(RuntimeError,))

        result = provider.generate("sys", "user")

        self.assertEqual(result, "from-fallback")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 1)

    def test_unrecognized_primary_error_propagates_without_falling_back(self) -> None:
        primary = _FakeProvider("primary", error=ValueError("unexpected bug"))
        fallback = _FakeProvider("fallback", response="from-fallback")
        provider = FallbackProvider(primary, fallback, primary_error_types=(RuntimeError,))

        with self.assertRaises(ValueError):
            provider.generate("sys", "user")

        self.assertEqual(fallback.calls, 0)

    def test_name_and_model_reflect_primary(self) -> None:
        primary = _FakeProvider("gemini", model="gemini-2.5-flash")
        fallback = _FakeProvider("ollama", model="qwen2.5:3b")
        provider = FallbackProvider(primary, fallback, primary_error_types=(RuntimeError,))

        self.assertEqual(provider.name, "gemini->ollama")
        self.assertEqual(provider.model, "gemini-2.5-flash")


class AutoProviderFactoryTests(unittest.TestCase):

    def test_auto_returns_plain_ollama_when_gemini_not_configured(self) -> None:
        from providers.ollama_provider import OllamaProvider

        with patch.object(config, "GEMINI_API_KEY", ""):
            provider = create_provider("auto")

        self.assertIsInstance(provider, OllamaProvider)

    def test_auto_wraps_gemini_with_ollama_fallback_when_gemini_configured(self) -> None:
        with patch.object(config, "GEMINI_API_KEY", "test-key"):
            provider = create_provider("auto")

        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(provider.name, "gemini->ollama")


class AutoProviderRealClassesIntegrationTests(unittest.TestCase):
    """Exercises the real GeminiProvider + OllamaProvider composition, transport mocked."""

    def test_falls_back_to_ollama_when_gemini_call_fails(self) -> None:
        # GEMINI_MODEL is pinned explicitly so this test exercises the
        # "generate_content fails -> fallback" path deterministically,
        # regardless of whatever happens to be in the real .env (an
        # empty value would instead exercise model discovery, which is
        # covered separately in tests/test_gemini_provider.py).
        with patch.object(config, "GEMINI_API_KEY", "test-key"), \
             patch.object(config, "GEMINI_MODEL", "gemini-2.5-flash"), \
             patch("providers.gemini_provider.genai.Client") as mock_gemini_client_cls, \
             patch("providers.ollama_provider.requests.post") as mock_post:

            # Simulate a network-level failure (not an APIError) — the
            # scenario the broadened except Exception in GeminiProvider
            # exists to cover.
            mock_gemini_client_cls.return_value.models.generate_content.side_effect = TimeoutError(
                "network timeout"
            )

            mock_response = MagicMock()
            mock_response.json.return_value = {"message": {"content": '{"documents": []}'}}
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response

            provider = create_provider("auto")
            result = provider.generate("system", "user")

        self.assertEqual(result, '{"documents": []}')
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
