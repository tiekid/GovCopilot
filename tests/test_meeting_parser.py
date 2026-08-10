"""Unit tests for agents/meeting_parser.py's regex-based metadata extraction.

Bug 4 regression coverage: title, location, and time were truncated at
the first line break because none of the regexes used re.DOTALL
(deliberately — "." must not swallow the next field's label line).
_extract_multiline fixes this by continuing to collect physical lines
after the first match until a blank line or another field label.
AIInvitationExtractor is never touched here — a trivial fake stands in
for it so these tests exercise only the regex/parsing logic.
"""

import unittest
from typing import List

from agents.meeting_parser import MeetingParserAgent
from models.document import MeetingDocument


class _FakeAIExtractor:
    """Stands in for AIInvitationExtractor — these tests are about regex parsing only."""

    def extract_documents(self, text: str):
        return []


class _FakeAIExtractorWithNumbers:
    """Returns a MeetingDocument per configured number, in order — used to
    test agenda_item_index assignment without touching the real AI path."""

    def __init__(self, numbers: List[str]) -> None:
        self._numbers = numbers

    def extract_documents(self, text: str) -> List[MeetingDocument]:
        return [MeetingDocument(number=n) for n in self._numbers]


class MeetingParserAgentTests(unittest.TestCase):

    def setUp(self) -> None:
        self.parser = MeetingParserAgent(ai_extractor=_FakeAIExtractor())

    def test_title_wrapped_across_two_lines_is_not_truncated(self) -> None:
        text = (
            "V/v: Họp thành viên\n"
            "Ủy ban nhân dân tỉnh\n"
            "\n"
            "Kính gửi: ...\n"
        )
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_name, "Họp thành viên Ủy ban nhân dân tỉnh")

    def test_title_on_single_line_still_works(self) -> None:
        text = "V/v: Họp giao ban tháng\n\nKính gửi: ...\n"
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_name, "Họp giao ban tháng")

    def test_title_continuation_stops_at_next_field_label(self) -> None:
        text = "V/v: Họp thành viên\nChủ trì: Ông Nguyễn Văn A\n"
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_name, "Họp thành viên")
        self.assertEqual(meeting.chairman, "Ông Nguyễn Văn A")

    def test_location_multiline_address_is_not_truncated(self) -> None:
        text = (
            "Địa điểm: Phòng họp số 01, tầng 2,\n"
            "Trụ sở UBND tỉnh Tây Ninh\n"
            "\n"
            "Thời gian: 08:00 ngày 03/08/2026\n"
        )
        meeting = self.parser.parse(text)
        self.assertEqual(
            meeting.location,
            "Phòng họp số 01, tầng 2, Trụ sở UBND tỉnh Tây Ninh",
        )

    def test_time_colon_format_hh_mm_ngay_date(self) -> None:
        text = "Thời gian: 08:00 ngày 03/08/2026\n"
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_time, "08:00")
        self.assertEqual(meeting.meeting_date, "03/08/2026")

    def test_time_gio_format_still_works(self) -> None:
        text = "Thời gian: 08 giờ 30, ngày 03/08/2026\n"
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_time, "08 giờ 30")
        self.assertEqual(meeting.meeting_date, "03/08/2026")

    def test_time_wrapped_across_lines(self) -> None:
        text = "Thời gian:\n08:00 ngày 03/08/2026\n\nĐịa điểm: Hội trường\n"
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_time, "08:00")
        self.assertEqual(meeting.meeting_date, "03/08/2026")

    def test_full_realistic_invitation(self) -> None:
        text = (
            "V/v: Họp thành viên\n"
            "Ủy ban nhân dân tỉnh\n"
            "\n"
            "Thời gian: 08:00 ngày 03/08/2026\n"
            "\n"
            "Địa điểm: Phòng họp số 01, tầng 2,\n"
            "Trụ sở UBND tỉnh Tây Ninh\n"
            "\n"
            "Chủ trì: Ông Nguyễn Văn A\n"
        )
        meeting = self.parser.parse(text)
        self.assertEqual(meeting.meeting_name, "Họp thành viên Ủy ban nhân dân tỉnh")
        self.assertEqual(meeting.meeting_time, "08:00")
        self.assertEqual(meeting.meeting_date, "03/08/2026")
        self.assertEqual(
            meeting.location,
            "Phòng họp số 01, tầng 2, Trụ sở UBND tỉnh Tây Ninh",
        )
        self.assertEqual(meeting.chairman, "Ông Nguyễn Văn A")


class AgendaItemIndexAssignmentTests(unittest.TestCase):
    """MeetingDocument.agenda_item_index — text-position correlation
    between the AI-extracted document list and the regex-extracted
    agenda (ND) blocks. Real evidence: neither extractor currently
    links the two on its own (see agents/normalization.py's plan)."""

    def test_documents_are_mapped_to_the_nd_block_they_appear_in(self) -> None:
        text = (
            "1. Sở Xây dựng trình:\n"
            "Tờ trình số 9047/TTr-SXD về việc quy hoạch\n"
            "\n"
            "2. Sở Nội vụ trình:\n"
            "Tờ trình số 8232/TTr-SNV về việc nhân sự\n"
        )
        parser = MeetingParserAgent(
            ai_extractor=_FakeAIExtractorWithNumbers(["9047/TTr-SXD", "8232/TTr-SNV"])
        )

        meeting = parser.parse(text)

        by_number = {d.number: d for d in meeting.documents}
        self.assertEqual(by_number["9047/TTr-SXD"].agenda_item_index, 1)
        self.assertEqual(by_number["8232/TTr-SNV"].agenda_item_index, 2)

    def test_document_number_not_found_in_text_stays_unassigned_and_logs_warning(self) -> None:
        text = "1. Sở Xây dựng trình:\nTờ trình số 9047/TTr-SXD về việc quy hoạch\n"
        parser = MeetingParserAgent(
            ai_extractor=_FakeAIExtractorWithNumbers(["9047/TTr-SXD", "9999/TTr-GHOST"])
        )

        with self.assertLogs("agents.meeting_parser", level="WARNING") as logs:
            meeting = parser.parse(text)

        by_number = {d.number: d for d in meeting.documents}
        self.assertEqual(by_number["9047/TTr-SXD"].agenda_item_index, 1)
        self.assertIsNone(by_number["9999/TTr-GHOST"].agenda_item_index)
        self.assertTrue(any("9999/TTr-GHOST" in message for message in logs.output))

    def test_no_agenda_items_leaves_every_document_unassigned_and_logs_warning(self) -> None:
        text = "Kính gửi: ...\nTờ trình số 9047/TTr-SXD về việc quy hoạch\n"
        parser = MeetingParserAgent(ai_extractor=_FakeAIExtractorWithNumbers(["9047/TTr-SXD"]))

        with self.assertLogs("agents.meeting_parser", level="WARNING") as logs:
            meeting = parser.parse(text)

        self.assertIsNone(meeting.documents[0].agenda_item_index)
        self.assertTrue(any("No agenda items" in message for message in logs.output))

    def test_document_referenced_before_the_first_nd_heading_stays_unassigned(self) -> None:
        # A document mentioned in a preamble, before any "N. <agency> trình:"
        # line, has no ND block before it — must not be guessed into ND01.
        text = (
            "Kèm theo Tờ trình số 9047/TTr-SXD\n"
            "\n"
            "1. Sở Xây dựng trình:\n"
            "Tờ trình số 8232/TTr-SNV về việc quy hoạch\n"
        )
        parser = MeetingParserAgent(
            ai_extractor=_FakeAIExtractorWithNumbers(["9047/TTr-SXD", "8232/TTr-SNV"])
        )

        meeting = parser.parse(text)

        by_number = {d.number: d for d in meeting.documents}
        self.assertIsNone(by_number["9047/TTr-SXD"].agenda_item_index)
        self.assertEqual(by_number["8232/TTr-SNV"].agenda_item_index, 1)


if __name__ == "__main__":
    unittest.main()
