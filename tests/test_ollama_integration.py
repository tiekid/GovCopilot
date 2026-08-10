"""Live integration test against a real local Ollama server.

Requires Ollama running locally with the model configured in
config.OLLAMA_MODEL pulled and available. Not part of routine
automated runs — run explicitly:

    python -m tests.test_ollama_integration
"""

import unittest

from ai.invitation_extractor import AIInvitationExtractor
from providers.ollama_provider import OllamaProvider

_SAMPLE_INVITATION = """
GIẤY MỜI HỌP

Kính mời quý đại biểu tham dự cuộc họp về việc xem xét các nội dung sau:

1. Sở Tài chính trình: Tờ trình số 9365/STC-
ĐTC về việc phê duyệt kế hoạch đầu tư công.

2. Sở Tài chính trình: Báo cáo số 9949/BC-
STC về tình hình thực hiện ngân sách.

Đề nghị các đại biểu nghiên cứu trước Tờ trình số 9365/STC-ĐTC
đã gửi kèm theo giấy mời này.

Trân trọng kính mời.
"""


class OllamaIntegrationTest(unittest.TestCase):
    """Exercises the real Ollama HTTP API end to end (no CLI, no mocks)."""

    def test_extracts_expected_documents_with_dedup(self) -> None:
        extractor = AIInvitationExtractor(provider=OllamaProvider())

        documents = extractor.extract_documents(_SAMPLE_INVITATION)
        numbers = [d.number for d in documents]

        self.assertIn("9365/STC-ĐTC", numbers)
        self.assertIn("9949/BC-STC", numbers)
        self.assertEqual(numbers.count("9365/STC-ĐTC"), 1)


if __name__ == "__main__":
    unittest.main()
