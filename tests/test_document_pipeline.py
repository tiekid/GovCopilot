"""Unit tests for pipeline/document_pipeline.py's parse()/process_documents() split.

Bug 1 fix: parse() must not require vb_search_agent/download_agent (so
it can run before a BrowserSession exists), and process_documents()
must fail clearly, not silently, if they're missing. run() must still
behave exactly as before for any caller using it as one call.

The attachment-section reopen-once workflow lives entirely inside
DownloadAgent now (agents/download.py) — process_documents() calls
download() exactly once per document, passing its progress callback
through. See tests/test_download_agent.py for the reopen behavior
itself.
"""

import unittest
from dataclasses import dataclass
from typing import List, Optional

from models.document import MeetingDocument
from models.meeting import Meeting
from pipeline.document_pipeline import DocumentPipeline


class _FakeMeetingParser:
    def __init__(self, meeting: Meeting) -> None:
        self._meeting = meeting

    def parse(self, text: str) -> Meeting:
        return self._meeting


@dataclass
class _FakeSearchResult:
    document: MeetingDocument
    success: bool
    found: bool
    error: Optional[str] = None


class _FakeVBSearchAgent:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def search(self, document: MeetingDocument) -> _FakeSearchResult:
        self.calls.append(document.number)
        return _FakeSearchResult(document=document, success=True, found=True)


@dataclass
class _FakeDownloadResult:
    document: MeetingDocument
    success: bool
    error: Optional[str] = None


class _FakeDownloadAgent:
    def __init__(self) -> None:
        self.calls: List[str] = []
        self.progress_callbacks_received = 0

    def download(self, document: MeetingDocument, progress_callback=None) -> _FakeDownloadResult:
        self.calls.append(document.number)
        if progress_callback is not None:
            self.progress_callbacks_received += 1
        return _FakeDownloadResult(document=document, success=True)


@dataclass
class _FakeNormalizedGroup:
    ma_nd: str


class _FakeNormalizationAgent:
    def __init__(self) -> None:
        self.calls: int = 0

    def normalize(self, meeting: Meeting) -> List[_FakeNormalizedGroup]:
        self.calls += 1
        return [_FakeNormalizedGroup(ma_nd="ND01")]


def _read_invitation_stub(_path: str) -> str:
    return "invitation text"


class DocumentPipelineSplitTests(unittest.TestCase):

    def setUp(self) -> None:
        self.meeting = Meeting(
            meeting_name="Test meeting",
            documents=[MeetingDocument(number="1234/TTr-XYZ")],
        )
        self.meeting_parser = _FakeMeetingParser(self.meeting)

    def test_parse_does_not_require_search_or_download_agent(self) -> None:
        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            read_invitation=_read_invitation_stub,
        )

        meeting = pipeline.parse("some/path.pdf")

        self.assertIs(meeting, self.meeting)

    def test_process_documents_raises_clearly_when_agents_missing(self) -> None:
        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            read_invitation=_read_invitation_stub,
        )

        with self.assertRaises(RuntimeError):
            pipeline.process_documents(self.meeting)

    def test_process_documents_searches_and_downloads_when_agents_present(self) -> None:
        vb_search_agent = _FakeVBSearchAgent()
        download_agent = _FakeDownloadAgent()

        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            vb_search_agent=vb_search_agent,
            download_agent=download_agent,
            read_invitation=_read_invitation_stub,
        )

        pipeline.process_documents(self.meeting)

        self.assertEqual(vb_search_agent.calls, ["1234/TTr-XYZ"])
        self.assertEqual(download_agent.calls, ["1234/TTr-XYZ"])

    def test_process_documents_calls_download_exactly_once_per_document(self) -> None:
        """The reopen-if-incomplete workflow lives inside DownloadAgent
        now — the pipeline itself never retries, never calls download()
        more than once per document."""

        vb_search_agent = _FakeVBSearchAgent()
        download_agent = _FakeDownloadAgent()

        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            vb_search_agent=vb_search_agent,
            download_agent=download_agent,
            read_invitation=_read_invitation_stub,
        )

        pipeline.process_documents(self.meeting)

        self.assertEqual(len(download_agent.calls), 1)
        self.assertEqual(download_agent.progress_callbacks_received, 1)

    def test_run_still_does_both_steps_in_one_call(self) -> None:
        vb_search_agent = _FakeVBSearchAgent()
        download_agent = _FakeDownloadAgent()

        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            vb_search_agent=vb_search_agent,
            download_agent=download_agent,
            read_invitation=_read_invitation_stub,
        )

        result = pipeline.run("some/path.pdf")

        self.assertIs(result, self.meeting)
        self.assertEqual(vb_search_agent.calls, ["1234/TTr-XYZ"])
        self.assertEqual(download_agent.calls, ["1234/TTr-XYZ"])

    def test_normalize_documents_raises_clearly_when_agent_missing(self) -> None:
        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            read_invitation=_read_invitation_stub,
        )

        with self.assertRaises(RuntimeError):
            pipeline.normalize_documents(self.meeting)

    def test_normalize_documents_calls_normalization_agent(self) -> None:
        normalization_agent = _FakeNormalizationAgent()

        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            normalization_agent=normalization_agent,
            read_invitation=_read_invitation_stub,
        )

        groups = pipeline.normalize_documents(self.meeting)

        self.assertEqual(normalization_agent.calls, 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].ma_nd, "ND01")

    def test_normalize_documents_reports_progress(self) -> None:
        normalization_agent = _FakeNormalizationAgent()

        pipeline = DocumentPipeline(
            meeting_parser=self.meeting_parser,
            normalization_agent=normalization_agent,
            read_invitation=_read_invitation_stub,
        )

        messages: List[str] = []
        pipeline.normalize_documents(self.meeting, progress_callback=messages.append)

        self.assertIn("Normalizing documents...", messages)
        self.assertTrue(any("1 agenda group" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
