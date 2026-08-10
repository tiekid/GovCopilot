"""Unit tests for providers/gemini_provider.py.

The google-genai SDK is fully mocked (patched at the point of use in
providers.gemini_provider) — no network access, no real API key
required, no real API calls made.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.genai import errors

from providers.ai_provider import ProviderConfigurationError
from providers.gemini_provider import (
    GeminiProvider,
    GeminiProviderError,
    list_text_generation_models,
    select_first_text_generation_model,
)


class GeminiProviderTests(unittest.TestCase):

    def test_missing_api_key_raises_configuration_error_without_touching_sdk(self) -> None:
        with patch("providers.gemini_provider.genai.Client") as mock_client_cls:
            with self.assertRaises(ProviderConfigurationError):
                GeminiProvider(api_key="", model="gemini-2.5-flash")

            mock_client_cls.assert_not_called()

    def test_generate_calls_sdk_with_expected_arguments_and_returns_text(self) -> None:
        mock_response = SimpleNamespace(text="{\"documents\": []}")
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client) as mock_client_cls:
            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
            result = provider.generate("system prompt text", "user prompt text")

        self.assertEqual(result, "{\"documents\": []}")
        mock_client_cls.assert_called_once_with(api_key="test-key")

        _, kwargs = mock_client.models.generate_content.call_args
        self.assertEqual(kwargs["model"], "gemini-2.5-flash")
        self.assertEqual(kwargs["contents"], "user prompt text")
        self.assertEqual(kwargs["config"].system_instruction, "system prompt text")
        self.assertEqual(kwargs["config"].temperature, 0)

    def test_generate_wraps_sdk_api_error(self) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = errors.APIError(
            code=401, response_json={"error": {"message": "invalid API key"}}
        )

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            provider = GeminiProvider(api_key="bad-key", model="gemini-2.5-flash")

            with self.assertRaises(GeminiProviderError):
                provider.generate("system", "user")

    def test_generate_raises_when_response_has_no_text(self) -> None:
        mock_response = SimpleNamespace(text=None)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

            with self.assertRaises(GeminiProviderError):
                provider.generate("system", "user")

    def test_name_and_model_properties(self) -> None:
        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        self.assertEqual(provider.name, "gemini")
        self.assertEqual(provider.model, "gemini-2.5-flash")


class ListTextGenerationModelsTests(unittest.TestCase):

    def test_returns_only_models_supporting_text_generation_stripped_of_prefix(self) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent", "countTokens"]),
            SimpleNamespace(name="models/embedding-001", supported_actions=["embedContent"]),
            SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
        ]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            models = list_text_generation_models("test-key")

        self.assertEqual(models, ["gemini-2.5-flash", "gemini-2.5-pro"])

    def test_raises_configuration_error_without_touching_sdk_when_key_missing(self) -> None:
        with patch("providers.gemini_provider.genai.Client") as mock_client_cls:
            with self.assertRaises(ProviderConfigurationError):
                list_text_generation_models("")

            mock_client_cls.assert_not_called()

    def test_wraps_listing_failure(self) -> None:
        with patch("providers.gemini_provider.genai.Client", side_effect=RuntimeError("network down")):
            with self.assertRaises(GeminiProviderError):
                list_text_generation_models("test-key")

    def test_select_first_raises_when_no_text_model_available(self) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/embedding-001", supported_actions=["embedContent"]),
        ]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            with self.assertRaises(GeminiProviderError):
                select_first_text_generation_model("test-key")

    def test_select_first_returns_first_match(self) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
        ]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            selected = select_first_text_generation_model("test-key")

        self.assertEqual(selected, "gemini-2.5-flash")

    def test_select_first_skips_excluded_model(self) -> None:
        # Regression test for a real, observed Gemini behavior: the API
        # can still list a model as text-generation-capable while it
        # 404s "no longer available to new users" for a given key — so
        # picking "just the first result" again would loop forever.
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
        ]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            selected = select_first_text_generation_model("test-key", exclude={"gemini-2.5-flash"})

        self.assertEqual(selected, "gemini-2.5-pro")

    def test_select_first_raises_when_only_excluded_model_available(self) -> None:
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
        ]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client):
            with self.assertRaises(GeminiProviderError):
                select_first_text_generation_model("test-key", exclude={"gemini-2.5-flash"})


class ModelDiscoveryAndSelfHealTests(unittest.TestCase):
    """No hardcoded model: generate() discovers one lazily, and self-heals on 404."""

    def test_generate_discovers_and_persists_model_when_none_configured(self) -> None:
        mock_response = SimpleNamespace(text='{"documents": []}')
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.return_value = mock_response

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="")
            result = provider.generate("system", "user")

        self.assertEqual(result, '{"documents": []}')
        self.assertEqual(provider.model, "gemini-2.5-flash")
        mock_set_config_value.assert_called_once_with("GEMINI_MODEL", "gemini-2.5-flash")

    def test_generate_retries_and_persists_replacement_on_404_not_found(self) -> None:
        not_found = errors.APIError(code=404, response_json={"error": {"status": "NOT_FOUND", "message": "model retired"}})

        mock_response = SimpleNamespace(text='{"documents": []}')
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash-002", supported_actions=["generateContent"]),
        ]
        # First call (with the stale configured model) 404s; the retry
        # call (with the freshly discovered model) succeeds.
        mock_client.models.generate_content.side_effect = [not_found, mock_response]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash-retired")
            result = provider.generate("system", "user")

        self.assertEqual(result, '{"documents": []}')
        self.assertEqual(provider.model, "gemini-2.5-flash-002")
        mock_set_config_value.assert_called_once_with("GEMINI_MODEL", "gemini-2.5-flash-002")
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

    def test_generate_skips_still_listed_but_retired_model_and_never_picks_pro(self) -> None:
        # Reproduces the real scenario found via live testing:
        # models.list() still includes the retired model (still first
        # in the list) and a pro-tier model (zero free-tier quota,
        # confirmed in production) — the replacement must be a flash
        # model, and must be the preferred one (gemini-flash-latest),
        # never gemini-2.5-pro even though it's technically available.
        not_found = errors.APIError(
            code=404,
            response_json={
                "error": {
                    "status": "NOT_FOUND",
                    "message": "This model models/gemini-2.5-flash is no longer available to new users.",
                }
            },
        )

        mock_response = SimpleNamespace(text='{"documents": []}')
        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-flash-latest", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.side_effect = [not_found, mock_response]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
            result = provider.generate("system", "user")

        self.assertEqual(result, '{"documents": []}')
        self.assertEqual(provider.model, "gemini-flash-latest")
        self.assertNotEqual(provider.model, "gemini-2.5-pro")
        mock_set_config_value.assert_called_once_with("GEMINI_MODEL", "gemini-flash-latest")

    def test_generate_never_selects_pro_model_even_as_last_resort(self) -> None:
        # Only a pro-tier model remains after excluding the failed
        # model — per requirement, this must raise, not fall back to
        # pro.
        not_found = errors.APIError(
            code=404, response_json={"error": {"status": "NOT_FOUND", "message": "retired"}}
        )

        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.side_effect = not_found

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

            with self.assertRaises(GeminiProviderError):
                provider.generate("system", "user")

        mock_set_config_value.assert_not_called()

    def test_generate_prefers_flash_lite_over_2_0_flash_when_flash_latest_absent(self) -> None:
        not_found = errors.APIError(
            code=404, response_json={"error": {"status": "NOT_FOUND", "message": "retired"}}
        )
        mock_response = SimpleNamespace(text='{"documents": []}')

        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.0-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-2.5-flash-lite", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.side_effect = [not_found, mock_response]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value"):

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
            provider.generate("system", "user")

        self.assertEqual(provider.model, "gemini-2.5-flash-lite")

    def test_generate_falls_back_to_any_remaining_flash_model(self) -> None:
        # None of the three preferred names are present — falls back
        # to the first remaining flash model in API-listed order.
        not_found = errors.APIError(
            code=404, response_json={"error": {"status": "NOT_FOUND", "message": "retired"}}
        )
        mock_response = SimpleNamespace(text='{"documents": []}')

        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-flash-experimental", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.side_effect = [not_found, mock_response]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value"):

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
            provider.generate("system", "user")

        self.assertEqual(provider.model, "gemini-flash-experimental")

    def test_replacement_only_cached_after_confirmed_success_not_before(self) -> None:
        # If the retry with the replacement model ALSO fails, the
        # provider must not have switched/cached/persisted it.
        not_found = errors.APIError(
            code=404, response_json={"error": {"status": "NOT_FOUND", "message": "retired"}}
        )

        mock_client = MagicMock()
        mock_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-flash-latest", supported_actions=["generateContent"]),
        ]
        mock_client.models.generate_content.side_effect = [not_found, RuntimeError("also failed")]

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

            with self.assertRaises(GeminiProviderError):
                provider.generate("system", "user")

        self.assertEqual(provider.model, "gemini-2.5-flash")
        mock_set_config_value.assert_not_called()

    def test_generate_raises_clearly_when_404_and_no_replacement_available(self) -> None:
        not_found = errors.APIError(code=404, response_json={"error": {"status": "NOT_FOUND", "message": "model retired"}})

        mock_client = MagicMock()
        mock_client.models.list.return_value = []  # nothing to fall back to
        mock_client.models.generate_content.side_effect = not_found

        with patch("providers.gemini_provider.genai.Client", return_value=mock_client), \
             patch("providers.gemini_provider.set_config_value") as mock_set_config_value:

            provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash-retired")

            with self.assertRaises(GeminiProviderError):
                provider.generate("system", "user")

        mock_set_config_value.assert_not_called()


if __name__ == "__main__":
    unittest.main()
