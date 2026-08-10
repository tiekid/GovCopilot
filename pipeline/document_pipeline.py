"""Orchestrates the existing agents into a single document pipeline.

Reads a meeting invitation, parses it, and for every referenced
document searches VBĐH and downloads it if found. This module
coordinates existing agents only — it duplicates no agent's logic,
never parses PDFs/DOCX directly, never performs AI analysis or export,
and never touches Playwright directly (no Page, no BrowserSession, no
selectors).
"""

import logging
from typing import Callable, Optional

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
        vb_search_agent: Optional[VBSearchAgent] = None,
        download_agent: Optional[DownloadAgent] = None,
        read_invitation: Callable[[str], str] = _read_invitation_file,
    ) -> None:
        # vb_search_agent/download_agent are optional because parse()
        # doesn't need them — they depend on an open BrowserSession,
        # which a caller may not have yet at parse time (see Bug 1 in
        # docs/09_LESSONS_LEARNED.md). process_documents() requires
        # both and raises clearly if either is missing.
        self._meeting_parser = meeting_parser
        self._vb_search_agent = vb_search_agent
        self._download_agent = download_agent
        self._read_invitation = read_invitation

    def run(
        self,
        invitation_path: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Meeting:
        """Full pipeline: parse, then search/download every document.

        Equivalent to calling parse() followed by process_documents().
        Kept as one call for any caller that doesn't need the two
        halves to happen at different times (unlike PipelineWorker,
        which runs parse() before opening the browser/waiting for
        login — see Bug 1 in docs/09_LESSONS_LEARNED.md).
        """

        meeting = self.parse(invitation_path, progress_callback)

        return self.process_documents(meeting, progress_callback)

    def parse(
        self,
        invitation_path: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Meeting:
        """Read and parse the invitation only — no VBĐH interaction.

        Split out from run() so a caller can do this before opening
        the browser / waiting for login, instead of after: parsing
        (including the AI call) doesn't need the browser at all, and
        there is no reason it should block behind an unrelated login
        wait.
        """

        def report(message: str) -> None:
            logger.info(message)
            if progress_callback is not None:
                progress_callback(message)

        logger.info("Parsing invitation: %s", invitation_path)

        report("Reading invitation...")
        text = self._read_invitation(invitation_path)

        meeting = self._meeting_parser.parse(text)
        report("Meeting parsed.")

        report(f"Found {len(meeting.documents)} referenced document(s).")

        return meeting

    def process_documents(
        self,
        meeting: Meeting,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Meeting:
        """Search VBĐH and download every document already on `meeting`.

        Unchanged search/download loop, only now callable on an
        already-parsed Meeting rather than always re-parsing first.
        """

        if self._vb_search_agent is None or self._download_agent is None:
            raise RuntimeError(
                "DocumentPipeline.process_documents() requires vb_search_agent "
                "and download_agent (construct DocumentPipeline with both, or "
                "call parse() only until they're available)."
            )

        def report(message: str) -> None:
            logger.info(message)
            if progress_callback is not None:
                progress_callback(message)

        total = len(meeting.documents)

        downloaded_count = 0
        not_found_count = 0
        error_count = 0

        for index, document in enumerate(meeting.documents, start=1):

            report(f"Searching document: {document.number}...")

            try:
                search_result = self._vb_search_agent.search(document)

                if not search_result.success:
                    error_count += 1
                    report(f"✗ Error: {search_result.error}")
                elif not search_result.found:
                    not_found_count += 1
                    report("✗ Not found")
                else:
                    report("Opening detail...")

                    # DownloadAgent handles the one-reopen-if-incomplete
                    # workflow internally now (attachment section
                    # sometimes doesn't render on the first open — see
                    # docs/09_LESSONS_LEARNED.md) — no pipeline-level
                    # retry of the download or the whole document.
                    download_result = self._download_agent.download(document, progress_callback=report)

                    if download_result.success:
                        downloaded_count += 1
                        report("✓ Downloaded.")
                    else:
                        error_count += 1
                        report(f"✗ Error: {download_result.error}")

            except Exception as exc:
                error_count += 1
                logger.exception(
                    "Pipeline step failed for document number %s", document.number
                )
                report(f"✗ Error: {exc}")

            report(f"Processing {index}/{total} documents...")

        report("Completed.")
        report(f"Downloaded: {downloaded_count}")
        report(f"Not found: {not_found_count}")
        report(f"Errors: {error_count}")

        logger.info(
            "Document pipeline complete: %d document(s) processed",
            total,
        )

        return meeting
