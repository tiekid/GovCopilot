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

from agents.meeting_parser import MeetingParserAgent


class _FakeAIExtractor:
    """Stands in for AIInvitationExtractor — these tests are about regex parsing only."""

    def extract_documents(self, text: str):
        return []


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


if __name__ == "__main__":
    unittest.main()
