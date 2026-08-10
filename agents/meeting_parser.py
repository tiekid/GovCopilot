"""Agent that parses meeting invitation text into a structured Meeting object."""

import logging
import re
from typing import List, Optional, Pattern, Tuple

from ai.invitation_extractor import AIInvitationExtractor
from models.document import MeetingDocument
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

# Supports "08 giờ [30]", "08h[30]", and "08:00" — the source invitation
# has been observed to use any of the three.
_HOUR_PATTERN: Pattern[str] = re.compile(
    r"\d{1,2}\s*(?:giờ\s*\d{0,2}|:\d{2}|h\s*\d{0,2})", re.IGNORECASE
)

# A line starting one of these labels marks the start of a *different*
# field — used to know where a wrapped value (title/location/time)
# ends, since none of the patterns above use re.DOTALL (deliberately:
# "." must not swallow the next field's label line).
_FIELD_LABEL_PATTERN: Pattern[str] = re.compile(
    r"^(?:V/v|Về việc|Chủ trì|Địa điểm|Thành phần|Kính mời|Thời gian)[:：]",
    re.IGNORECASE,
)


class MeetingParserAgent:
    """Parses meeting invitation text into a Meeting object.

    Meeting metadata (title, chairman, date, time, location,
    participants, agenda) is extracted with deterministic regex.
    Meeting.documents is authoritatively extracted by
    AIInvitationExtractor — regex-based document extraction
    (agents/document_extractor.py) is legacy and not used here.
    """

    def __init__(self, ai_extractor: Optional[AIInvitationExtractor] = None) -> None:
        self._ai_extractor = ai_extractor or AIInvitationExtractor()

    def parse(self, text: str) -> Meeting:

        meeting = Meeting(
            meeting_name=self._extract_multiline(text, _TITLE_PATTERN),
            chairman=self._extract_first(text, _CHAIRMAN_PATTERN),
            location=self._extract_multiline(text, _LOCATION_PATTERN),
            participants=self._extract_first(text, _PARTICIPANTS_PATTERN),
        )

        time_line = self._extract_multiline(text, _TIME_LINE_PATTERN)

        if time_line:
            meeting.meeting_date = self._extract_first(time_line, _DATE_PATTERN, has_group=False)
            meeting.meeting_time = self._extract_first(time_line, _HOUR_PATTERN, has_group=False)

        meeting.agenda = self._extract_agenda(text)
        meeting.documents = self._ai_extractor.extract_documents(text)

        self._assign_agenda_item_indices(text, meeting.agenda, meeting.documents)

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

    def _assign_agenda_item_indices(
        self, text: str, agenda: List[AgendaItem], documents: List[MeetingDocument]
    ) -> None:
        """Map each document to the ND (AgendaItem) it was referenced under.

        Text-position correlation: each AgendaItem's heading line marks
        where its ND block starts in the invitation text; a document
        belongs to whichever block's heading is the last one appearing
        before that document number's own first occurrence in the
        text. Mutates `documents` in place.

        Never invents a mapping — if a document's number doesn't
        actually occur in the invitation text, or there are no agenda
        items at all, agenda_item_index stays None and a WARNING is
        logged so the gap is visible, not silently dropped (the caller,
        NormalizationAgent, groups these as "unassigned ND").
        """

        if not agenda:
            for document in documents:
                document.agenda_item_index = None
            if documents:
                logger.warning(
                    "No agenda items parsed from invitation text; %d document(s) "
                    "left without an agenda_item_index",
                    len(documents),
                )
            return

        boundaries = self._agenda_heading_offsets(text, agenda)

        for document in documents:
            position = text.find(document.number)

            if position == -1:
                document.agenda_item_index = None
                logger.warning(
                    "Document number %s not found in invitation text; cannot "
                    "determine its agenda item (ND)",
                    document.number,
                )
                continue

            document.agenda_item_index = self._agenda_index_for_position(position, boundaries)

    @staticmethod
    def _agenda_heading_offsets(text: str, agenda: List[AgendaItem]) -> List[Tuple[int, int]]:
        """Character offset where each agenda item's heading line starts, in order.

        Re-scans line by line (like _extract_agenda) rather than
        reusing its output directly, because offsets specifically
        require locating each heading line's real position in `text`
        via `text.index()` — computing offsets by summing line lengths
        instead would drift against "\\r\\n" vs "\\n" line endings and
        silently misalign document positions found later via
        `text.find()`. Searches strictly forward (`search_from`
        advances past each match) so agenda items are matched in the
        same order _extract_agenda produced them.
        """

        boundaries: List[Tuple[int, int]] = []
        search_from = 0

        for item in agenda:
            for line in text[search_from:].splitlines():
                if _AGENDA_PATTERN.match(line.strip()):
                    offset = text.index(line, search_from)
                    boundaries.append((offset, item.index))
                    search_from = offset + len(line)
                    break

        return boundaries

    @staticmethod
    def _agenda_index_for_position(position: int, boundaries: List[Tuple[int, int]]) -> Optional[int]:
        """The agenda item whose heading is the last one before `position`."""

        matched_index: Optional[int] = None

        for offset, index in boundaries:
            if offset <= position:
                matched_index = index
            else:
                break

        return matched_index

    @staticmethod
    def _extract_first(text: str, pattern: Pattern[str], has_group: bool = True) -> str:

        match = pattern.search(text)

        if not match:
            return ""

        return (match.group(1) if has_group else match.group(0)).strip()

    @staticmethod
    def _extract_multiline(text: str, pattern: Pattern[str]) -> str:
        """Like _extract_first, but continues across lines the source wrapped.

        `pattern` itself only ever captures up to the first line break
        ("." doesn't match "\\n", deliberately — see _FIELD_LABEL_PATTERN).
        This continues collecting subsequent physical lines after that
        first match as long as they're non-blank and don't start a new
        recognized field, then joins everything into one string —
        recovering a title/location/time value the source PDF/DOCX
        wrapped across multiple lines instead of truncating it.
        """

        match = pattern.search(text)

        if not match:
            return ""

        collected = [match.group(1).strip()]

        # (.+) is greedy and stops only at "\n" (never matches it), so
        # match.end() always lands right before that newline — the
        # first element of this split is always "" (the empty tail of
        # the line already captured in match.group(1)), not a real
        # subsequent line. Drop it, or a genuinely blank first
        # continuation line is indistinguishable from "nothing left to
        # capture" and the loop below stops before it ever starts.
        remaining_lines = text[match.end():].split("\n")[1:]

        for line in remaining_lines:
            stripped = line.strip()

            if not stripped or _FIELD_LABEL_PATTERN.match(stripped):
                break

            collected.append(stripped)

        return " ".join(part for part in collected if part)
