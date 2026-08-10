"""Unit tests for ai/invitation_extractor.py using a fake AIProvider.

Uses FakeProvider (tests/fakes.py) so these tests never call a real
AI backend — analogous to the FakePage tier described in
docs/TESTING.md, for AIProvider instead of Playwright's Page.
"""

import json
import unittest

from ai.invitation_extractor import AIInvitationExtractionError, AIInvitationExtractor
from tests.fakes import FakeProvider


class AIInvitationExtractorTests(unittest.TestCase):

    def test_parses_valid_response_into_documents(self) -> None:
        provider = FakeProvider(json.dumps({"documents": [{"number": "9365/STC-ĐTC"}]}))
        extractor = AIInvitationExtractor(provider=provider)

        documents = extractor.extract_documents("some invitation text")

        self.assertEqual([d.number for d in documents], ["9365/STC-ĐTC"])

    def test_removes_duplicates_preserving_order(self) -> None:
        provider = FakeProvider(
            json.dumps(
                {
                    "documents": [
                        {"number": "9365/STC-ĐTC"},
                        {"number": "9949/BC-STC"},
                        {"number": "9365/STC-ĐTC"},
                    ]
                }
            )
        )
        extractor = AIInvitationExtractor(provider=provider)

        documents = extractor.extract_documents("some invitation text")

        self.assertEqual([d.number for d in documents], ["9365/STC-ĐTC", "9949/BC-STC"])

    def test_normalizes_text_before_calling_provider(self) -> None:
        provider = FakeProvider(json.dumps({"documents": []}))
        extractor = AIInvitationExtractor(provider=provider)

        extractor.extract_documents("Số 9365/STC-\nĐTC cần xem xét.")

        self.assertIn("9365/STC-ĐTC", provider.last_user_prompt)
        self.assertNotIn("STC-\n", provider.last_user_prompt)

    def test_provider_is_called_exactly_once_per_extraction(self) -> None:
        provider = FakeProvider(json.dumps({"documents": []}))
        extractor = AIInvitationExtractor(provider=provider)

        extractor.extract_documents("some invitation text")

        self.assertEqual(provider.call_count, 1)

    def test_extracts_json_object_surrounded_by_extra_text(self) -> None:
        response = 'Here is the result:\n' + json.dumps({"documents": [{"number": "9365/STC-ĐTC"}]}) + '\nHope that helps!'
        provider = FakeProvider(response)
        extractor = AIInvitationExtractor(provider=provider)

        documents = extractor.extract_documents("some invitation text")

        self.assertEqual([d.number for d in documents], ["9365/STC-ĐTC"])

    def test_raises_when_no_json_object_present(self) -> None:
        provider = FakeProvider("not json, no braces at all")
        extractor = AIInvitationExtractor(provider=provider)

        with self.assertRaises(AIInvitationExtractionError):
            extractor.extract_documents("some invitation text")

    def test_raises_on_malformed_json(self) -> None:
        provider = FakeProvider('{"documents": [')
        extractor = AIInvitationExtractor(provider=provider)

        with self.assertRaises(AIInvitationExtractionError):
            extractor.extract_documents("some invitation text")

    def test_raises_when_multiple_top_level_json_objects_present(self) -> None:
        response = json.dumps({"documents": [{"number": "9365/STC-ĐTC"}]}) + " " + json.dumps({"documents": []})
        provider = FakeProvider(response)
        extractor = AIInvitationExtractor(provider=provider)

        with self.assertRaises(AIInvitationExtractionError):
            extractor.extract_documents("some invitation text")

    def test_raises_when_documents_field_missing(self) -> None:
        provider = FakeProvider(json.dumps({"unexpected": []}))
        extractor = AIInvitationExtractor(provider=provider)

        with self.assertRaises(AIInvitationExtractionError):
            extractor.extract_documents("some invitation text")

    def test_raises_when_entry_missing_number(self) -> None:
        provider = FakeProvider(json.dumps({"documents": [{"title": "no number here"}]}))
        extractor = AIInvitationExtractor(provider=provider)

        with self.assertRaises(AIInvitationExtractionError):
            extractor.extract_documents("some invitation text")


if __name__ == "__main__":
    unittest.main()
