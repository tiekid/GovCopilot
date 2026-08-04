"""Agent that extracts referenced document numbers from meeting invitation text."""

import logging
import re
from typing import List, Pattern, Tuple

from models.document import MeetingDocument

logger = logging.getLogger(__name__)

_AGENCY_PATTERN: Pattern[str] = re.compile(r"^\d+\.\s*(.+?)\s+trình[:：]", re.IGNORECASE)

_DOCUMENT_TYPE_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("Tờ trình", re.compile(r"Tờ trình\s+số\s+([0-9]+\/[A-Za-z\-]+)", re.IGNORECASE)),
    ("Báo cáo", re.compile(r"Báo cáo\s+số\s+([0-9]+\/[A-Za-z\-]+)", re.IGNORECASE)),
    ("Công văn", re.compile(r"Công văn\s+số\s+([0-9]+\/[A-Za-z\-]+)", re.IGNORECASE)),
)


class DocumentExtractorAgent:
    """Extracts every referenced document number from meeting invitation text."""

    def extract(self, text: str) -> List[MeetingDocument]:

        documents: List[MeetingDocument] = []

        current_agency = ""

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            agency_match = _AGENCY_PATTERN.match(line)

            if agency_match:
                current_agency = agency_match.group(1).strip()
                continue

            for document_type, pattern in _DOCUMENT_TYPE_PATTERNS:
                documents.extend(
                    self._extract_documents(line, current_agency, document_type, pattern)
                )

        logger.info("Extracted %d document(s) from invitation text", len(documents))

        return documents

    def _extract_documents(
        self,
        line: str,
        agency: str,
        document_type: str,
        pattern: Pattern[str],
    ) -> List[MeetingDocument]:

        result: List[MeetingDocument] = []

        for match in pattern.finditer(line):

            number = match.group(1)

            title = line[match.end():].lstrip(":").strip()

            result.append(
                MeetingDocument(
                    agency=agency,
                    document_type=document_type,
                    number=number,
                    title=title,
                )
            )

        return result


# Backward-compatible alias for the pre-refactor class name.
DocumentExtractor = DocumentExtractorAgent
