"""Unit tests for ai/text_normalizer.py."""

import unittest

from ai.text_normalizer import normalize_document_identifiers


class NormalizeDocumentIdentifiersTests(unittest.TestCase):

    def test_merges_wrapped_identifier_first_example(self) -> None:
        text = "Kính gửi văn bản 9365/STC-\nĐTC để xem xét."
        self.assertIn("9365/STC-ĐTC", normalize_document_identifiers(text))

    def test_merges_wrapped_identifier_second_example(self) -> None:
        text = "Báo cáo số 9949/BC-\nSTC gửi kèm."
        self.assertIn("9949/BC-STC", normalize_document_identifiers(text))

    def test_merges_multiple_wrapped_identifiers_in_same_text(self) -> None:
        text = "Tờ trình 9365/STC-\nĐTC và báo cáo 9949/BC-\nSTC kèm theo."
        normalized = normalize_document_identifiers(text)
        self.assertIn("9365/STC-ĐTC", normalized)
        self.assertIn("9949/BC-STC", normalized)

    def test_leaves_unwrapped_text_unchanged(self) -> None:
        text = "Công văn 1234/UBND-VX đã được ban hành."
        self.assertEqual(text, normalize_document_identifiers(text))


if __name__ == "__main__":
    unittest.main()
