"""Agent that parses meeting invitation text into a structured Meeting object."""

import logging
import re
from typing import List, Optional, Pattern

from agents.document_extractor import DocumentExtractorAgent
from models.meeting import AgendaItem, Meeting

logger = logging.getLogger(__name__)

_AGENDA_PATTERN: Pattern[str] = re.compile(r"^\d+\.\s*(.+?)\s+trình[:：]", re.IGNORECASE)

_TITLE_PATTERN: Pattern[str] = re.compile(r"(?:V/v|Về việc)[:：]\s*(.+)", re.IGNORECASE)
_CHAIRMAN_PATTERN: Pattern[str] = re.compile(r"Chủ trì[:：]\s*(.+)", re.IGNORECASE)
_LOCATION_PATTERN: Pattern[str] = re.compile(r"Địa điểm[:：]\s*(.+)", re.IGNORECASE)
_PARTICIPANTS_PATTERN: Pattern[str] = re.compile(
    r"(?:Thành phần|Kính mời)[:：]\s*(.+)", re.IGNORECASE
)
_TIME_LINE_PATTERN: Pattern[str] = re.compile(r"Thời gian[:：]\s*(.+)", re.IGNORECASE)
_DATE_PATTERN: Pattern[str] = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
_HOUR_PATTERN: Pattern[str] = re.compile(r"\d{1,2}\s*(?:giờ|h)\s*\d{0,2}", re.IGNORECASE)


class MeetingParserAgent:
    """Parses meeting invitation text into a Meeting object using deterministic regex."""

    def __init__(self, document_extractor: Optional[DocumentExtractorAgent] = None) -> None:
        self._document_extractor = document_extractor or DocumentExtractorAgent()

    def parse(self, text: str) -> Meeting:

        meeting = Meeting(
            meeting_name=self._extract_first(text, _TITLE_PATTERN),
            chairman=self._extract_first(text, _CHAIRMAN_PATTERN),
            location=self._extract_first(text, _LOCATION_PATTERN),
            participants=self._extract_first(text, _PARTICIPANTS_PATTERN),
        )

        time_line = self._extract_first(text, _TIME_LINE_PATTERN)

        if time_line:
            meeting.meeting_date = self._extract_first(time_line, _DATE_PATTERN, has_group=False)
            meeting.meeting_time = self._extract_first(time_line, _HOUR_PATTERN, has_group=False)

        meeting.agenda = self._extract_agenda(text)
        meeting.documents = self._document_extractor.extract(text)

        logger.info(
            "Parsed meeting '%s' with %d agenda item(s) and %d document(s)",
            meeting.meeting_name,
            len(meeting.agenda),
            len(meeting.documents),
        )

        return meeting

    def _extract_agenda(self, text: str) -> List[AgendaItem]:

        agenda: List[AgendaItem] = []

        index = 0

        for line in text.splitlines():

            line = line.strip()

            match = _AGENDA_PATTERN.match(line)

            if not match:
                continue

            index += 1

            agenda.append(
                AgendaItem(
                    index=index,
                    agency=match.group(1).strip(),
                    title=line[match.end():].lstrip(":").strip(),
                )
            )

        return agenda

    @staticmethod
    def _extract_first(text: str, pattern: Pattern[str], has_group: bool = True) -> str:

        match = pattern.search(text)

        if not match:
            return ""

        return (match.group(1) if has_group else match.group(0)).strip()
