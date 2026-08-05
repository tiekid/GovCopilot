"""Orchestrates the existing agents into a single document pipeline.

Reads a meeting invitation, parses it, and for every referenced
document searches VBĐH and downloads it if found. This module
coordinates existing agents only — it duplicates no agent's logic,
never parses PDFs/DOCX directly, never performs AI analysis or export,
and never touches Playwright directly (no Page, no BrowserSession, no
selectors).
"""

import logging
from typing import Callable

from agents.download import DownloadAgent
from agents.meeting_parser import MeetingParserAgent
from agents.vb_search import VBSearchAgent
from models.meeting import Meeting
from parser.invitation_reader import read_invitation as _read_invitation_file

logger = logging.getLogger(__name__)


class DocumentPipeline:
    """Coordinates MeetingParserAgent, VBSearchAgent, and DownloadAgent.

    Reads and parses the invitation, then for every referenced document
    searches VBĐH and downloads it if found, continuing past any single
    document's failure. Returns the updated Meeting object.
    """

    def __init__(
        self,
        meeting_parser: MeetingParserAgent,
        vb_search_agent: VBSearchAgent,
        download_agent: DownloadAgent,
        read_invitation: Callable[[str], str] = _read_invitation_file,
    ) -> None:
        self._meeting_parser = meeting_parser
        self._vb_search_agent = vb_search_agent
        self._download_agent = download_agent
        self._read_invitation = read_invitation

    def run(self, invitation_path: str) -> Meeting:

        logger.info("Running document pipeline for invitation: %s", invitation_path)

        text = self._read_invitation(invitation_path)
        meeting = self._meeting_parser.parse(text)

        for document in meeting.documents:
            try:
                result = self._vb_search_agent.search(document)

                if result.found:
                    self._download_agent.download(document)

            except Exception:
                logger.exception(
                    "Pipeline step failed for document number %s", document.number
                )
                continue

        logger.info(
            "Document pipeline complete: %d document(s) processed",
            len(meeting.documents),
        )

        return meeting
