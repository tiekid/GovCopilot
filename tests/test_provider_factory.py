"""Unit tests for providers/provider_factory.py.

No network access, no real SDKs exercised — GeminiProvider raises
ProviderConfigurationError with no API key (asserted directly, not
mocked), and the stub providers raise NotImplementedError only when
generate() is actually called, never at construction.
"""

import unittest
from unittest.mock import patch

import config
from providers.ai_provider import ProviderConfigurationError
from providers.claude_provider import ClaudeProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.provider_factory import UnknownProviderError, create_provider


class CreateProviderTests(unittest.TestCase):

    def test_creates_ollama_provider(self) -> None:
        provider = create_provider("ollama")
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.name, "ollama")

    def test_creates_gemini_provider_with_explicit_key(self) -> None:
        from providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(provider.name, "gemini")
        self.assertEqual(provider.model, "gemini-2.5-flash")

    def test_gemini_provider_without_api_key_raises_configuration_error(self) -> None:
        from providers.gemini_provider import GeminiProvider

        with self.assertRaises(ProviderConfigurationError):
            GeminiProvider(api_key="", model="gemini-2.5-flash")

    def test_create_provider_gemini_without_configured_key_raises_configuration_error(self) -> None:
        # Explicitly patched to "" regardless of the local .env, so this
        # test is deterministic — it verifies the "first run, nothing
        # configured yet" path, not the current machine's .env state.
        with patch.object(config, "GEMINI_API_KEY", ""):
            with self.assertRaises(ProviderConfigurationError):
                create_provider("gemini")

    def test_creates_openai_stub_provider(self) -> None:
        provider = create_provider("openai")
        self.assertIsInstance(provider, OpenAIProvider)
        with self.assertRaises(NotImplementedError):
            provider.generate("system", "user")

    def test_creates_claude_stub_provider(self) -> None:
        provider = create_provider("claude")
        self.assertIsInstance(provider, ClaudeProvider)
        with self.assertRaises(NotImplementedError):
            provider.generate("system", "user")

    def test_provider_name_is_case_insensitive(self) -> None:
        provider = create_provider("OLLAMA")
        self.assertIsInstance(provider, OllamaProvider)

    def test_unknown_provider_raises(self) -> None:
        with self.assertRaises(UnknownProviderError):
            create_provider("does-not-exist")

    def test_empty_provider_name_falls_back_to_configured_default(self) -> None:
        # "" behaves like omitting provider_name entirely — falls back
        # to config.AI_PROVIDER — it is not itself an unknown provider.
        with patch.object(config, "AI_PROVIDER", "ollama"):
            provider = create_provider("")
            self.assertIsInstance(provider, OllamaProvider)


if __name__ == "__main__":
    unittest.main()
