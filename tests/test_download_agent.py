"""FakePage tests for agents/download.py's diagnostic instrumentation
and the attachment-section reopen workflow.

docs/TESTING.md tier 2 (FakePage tests). Also verifies
logs/download/<number>.json is written with the expected fields for
each scenario.
"""

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from agents.download import (
    DownloadAgent,
    _DIAGNOSTICS_LOG_DIR,
    _DOWNLOAD_TIMEOUT_MESSAGE,
    _INCOMPLETE_DIALOG_MESSAGE,
    _MAX_DOWNLOAD_TIMEOUT_SECONDS,
)
from models.document import MeetingDocument
from tests.fake_page import (
    FakeBrowserSession,
    FakeDownload,
    FakeLocator,
    FakePage,
    FakeResponse,
)


def _read_diagnostics(document_number: str) -> dict:
    sanitized = document_number.replace("/", "_")
    path = _DIAGNOSTICS_LOG_DIR / f"{sanitized}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _attachment_table(row_count: int, no_data: bool = False) -> FakeLocator:
    """Builds a fake #tapTinDinhKem table with `row_count` real rows.

    Real markup: an empty table's placeholder is a `<tr class="noData">`
    *inside* tbody — the real row-count selector excludes it
    (`tbody tr:not(.noData)`), so this fake only ever puts real rows
    under that exact selector key.
    """
    return FakeLocator(
        count=1,
        sub_locators={"tbody tr:not(.noData)": FakeLocator(count=row_count)},
        text_matches={"Không có dữ liệu"} if no_data else set(),
    )


def _dialog(attachment_table: Optional[FakeLocator] = None) -> FakeLocator:
    sub_locators = {}
    if attachment_table is not None:
        sub_locators["#tapTinDinhKem"] = attachment_table
    return FakeLocator(count=1, visible=True, sub_locators=sub_locators)


def _close_button() -> FakeLocator:
    """Fake real close icon — _close_dialog() clicks this now, not Escape
    (see agents/download.py's _DIALOG_CLOSE_BUTTON_SELECTOR comment)."""
    return FakeLocator(count=1, visible=True)


@dataclass
class _FakeSearchResult:
    success: bool
    found: bool
    error: Optional[str] = None


class _FakeVBSearchAgent:
    """Records calls; returns configured results in order, repeating the last."""

    def __init__(self, results: Optional[List[_FakeSearchResult]] = None) -> None:
        self.calls: List[str] = []
        self._results = results if results is not None else [_FakeSearchResult(success=True, found=True)]

    def search(self, document: MeetingDocument) -> _FakeSearchResult:
        self.calls.append(document.number)
        index = min(len(self.calls) - 1, len(self._results) - 1)
        return self._results[index]


class DownloadAgentDiagnosticsTests(unittest.TestCase):

    def test_dialog_rendered_with_attachment_downloads_successfully(self) -> None:
        """Healthy case: attachment table has rows, download succeeds."""

        document = MeetingDocument(number="TEST/CASE-RENDERED-OK")

        dialog_locator = _dialog(_attachment_table(row_count=3))
        control_locator = FakeLocator(count=1, visible=True, enabled=True)
        close_button_locator = _close_button()

        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=FakeDownload(suggested_filename="attachment.pdf"),
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

            self.assertTrue(result.success)
            self.assertTrue(control_locator.clicked)
            self.assertEqual(document.downloaded, True)
            # Every exit path guarantees the dialog is closed — including
            # a clean, no-reopen-needed success (see module docstring's
            # E2E finding: leaving it open here is exactly what stalled
            # the next document's search in production).
            self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertTrue(diagnostics["dialog_opened"])
        self.assertTrue(diagnostics["dialog_rendered"])
        self.assertTrue(diagnostics["attachment_table_detected"])
        self.assertEqual(diagnostics["attachment_row_count"], 3)
        self.assertFalse(diagnostics["no_data_present"])
        self.assertFalse(diagnostics["reopened_dialog"])
        self.assertTrue(diagnostics["download_control_present"])
        self.assertTrue(diagnostics["download_click_performed"])
        self.assertTrue(diagnostics["download_event_received"])
        self.assertIsNone(diagnostics["error"])

    def test_no_data_present_is_recorded_but_no_longer_blocks_a_reopen(self) -> None:
        """Root cause fix: "Không có dữ liệu" is real (matches 6 unrelated
        tables in the dialog, not just attachments — see
        docs/09_LESSONS_LEARNED.md) so it's still recorded, but no
        longer used to decide anything. A genuinely-empty attachment
        table (0 real rows) is "incomplete" like any other — with no
        vb_search_agent collaborator, it fails without a reopen attempt.
        """

        document = MeetingDocument(number="TEST/CASE-NO-DATA")

        dialog_locator = _dialog(_attachment_table(row_count=0, no_data=True))
        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            }
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

            self.assertFalse(result.success)
            self.assertEqual(result.error, _INCOMPLETE_DIALOG_MESSAGE)
            # Still closed on exit even though no reopen was ever attempted.
            self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertTrue(diagnostics["dialog_opened"])
        self.assertTrue(diagnostics["attachment_table_detected"])
        self.assertEqual(diagnostics["attachment_row_count"], 0)
        self.assertTrue(diagnostics["no_data_present"])  # recorded...
        self.assertFalse(diagnostics["reopened_dialog"])  # ...but no vb_search_agent, so no reopen attempted
        self.assertFalse(diagnostics["download_click_performed"])  # ...and never clicked either

    def test_click_without_download_event_is_recorded_with_new_tab(self) -> None:
        """Click succeeds but no Playwright download event fires — a new tab opens instead."""

        document = MeetingDocument(number="TEST/CASE-NEW-TAB")

        dialog_locator = _dialog(_attachment_table(row_count=1))

        page: FakePage

        def open_new_tab_on_click() -> None:
            page.context.emit(
                "page", SimpleNamespace(url="https://vbdh.tayninh.gov.vn/viewer?file=abc.pdf")
            )

        control_locator = FakeLocator(count=1, visible=True, enabled=True, on_click=open_new_tab_on_click)
        close_button_locator = _close_button()

        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=None,
            raise_on_download_wait=PlaywrightTimeoutError("Timeout waiting for download event"),
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

            self.assertFalse(result.success)
            self.assertTrue(control_locator.clicked)
            # Timeout is a different problem now (not this fix's scope) —
            # still no retry/reopen, just a clean failure + dialog close
            # (via the real close button now, not Escape).
            self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertTrue(diagnostics["download_click_performed"])
        self.assertFalse(diagnostics["download_event_received"])
        self.assertTrue(diagnostics["new_tab_opened"])
        self.assertEqual(diagnostics["new_tab_url"], "https://vbdh.tayninh.gov.vn/viewer?file=abc.pdf")
        self.assertEqual(diagnostics["error"], _DOWNLOAD_TIMEOUT_MESSAGE)

    def test_inline_pdf_response_is_captured_without_download_event_or_new_tab(self) -> None:
        """VBĐH can serve the file inline instead of a Playwright download,
        a new tab, or a navigation — the last response's status/content-type
        is the only signal left."""

        document = MeetingDocument(number="TEST/CASE-INLINE-PDF")

        dialog_locator = _dialog(_attachment_table(row_count=1))

        page: FakePage

        def emit_inline_pdf_response_on_click() -> None:
            page.emit(
                "response",
                FakeResponse(
                    url="https://vbdh.tayninh.gov.vn/api/documents/9047/view",
                    status=200,
                    content_type="application/pdf",
                ),
            )

        control_locator = FakeLocator(
            count=1, visible=True, enabled=True, on_click=emit_inline_pdf_response_on_click
        )
        close_button_locator = _close_button()

        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=None,
            raise_on_download_wait=PlaywrightTimeoutError("Timeout waiting for download event"),
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

            self.assertFalse(result.success)
            self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertFalse(diagnostics["download_event_received"])
        self.assertFalse(diagnostics["new_tab_opened"])
        self.assertEqual(diagnostics["iframe_count"], 0)
        self.assertEqual(
            diagnostics["last_response_url"], "https://vbdh.tayninh.gov.vn/api/documents/9047/view"
        )
        self.assertEqual(diagnostics["last_response_status"], 200)
        self.assertEqual(diagnostics["last_response_content_type"], "application/pdf")

    def test_unexpected_exception_during_download_still_closes_dialog(self) -> None:
        """An error that isn't the timeout-shaped one (falls through to
        the generic except Exception handler) must still close the
        dialog on the way out — the exit guarantee covers every path,
        not just the ones with a dedicated except clause."""

        document = MeetingDocument(number="TEST/CASE-UNEXPECTED-EXCEPTION")

        dialog_locator = _dialog(_attachment_table(row_count=1))
        control_locator = FakeLocator(
            count=1, visible=True, enabled=True, click_error=RuntimeError("Unexpected VBĐH error")
        )
        close_button_locator = _close_button()

        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

        self.assertFalse(result.success)
        self.assertIn("Unexpected VBĐH error", result.error)
        self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertIn("Unexpected VBĐH error", diagnostics["error"])

    def test_iframe_embedded_viewer_is_counted(self) -> None:
        """An iframe-embedded viewer neither opens a new tab nor
        necessarily navigates the main frame — iframe_count is the signal."""

        document = MeetingDocument(number="TEST/CASE-IFRAME-VIEWER")

        dialog_locator = _dialog(_attachment_table(row_count=1))
        control_locator = FakeLocator(count=1, visible=True, enabled=True)
        close_button_locator = _close_button()

        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=None,
            raise_on_download_wait=PlaywrightTimeoutError("Timeout waiting for download event"),
            frames=[object(), object()],  # main frame + one iframe
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            agent.download(document)

        self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertEqual(diagnostics["iframe_count"], 1)


class AttachmentSectionReopenTests(unittest.TestCase):
    """Root cause fix: the dialog sometimes opens without the attachment
    section rendered; closing and reopening the same document once
    fixes it — confirmed real behavior. Never uses no_data_present."""

    def test_without_a_vb_search_agent_incomplete_dialog_fails_without_reopening(self) -> None:
        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": _dialog(attachment_table=None),
                "#formXuLy .close.icon:visible": close_button_locator,
            }
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))  # no vb_search_agent
            result = agent.download(MeetingDocument(number="TEST/CASE-NO-COLLABORATOR"))

        self.assertFalse(result.success)
        self.assertEqual(result.error, _INCOMPLETE_DIALOG_MESSAGE)
        # No reopen was ever attempted (no collaborator) — but the exit
        # guarantee still closes the still-open original dialog.
        self.assertTrue(close_button_locator.clicked)

    def test_missing_attachment_table_triggers_one_reopen_then_succeeds(self) -> None:
        document = MeetingDocument(number="9047/TTr-SXD")

        # First open: no #tapTinDinhKem at all. After "reopen", the fake
        # VBSearchAgent's search() succeeds — but the SAME FakePage still
        # needs to reflect a complete dialog on the second inspection, so
        # swap in a page whose dialog locator now has a working table.
        dialog_with_table = _dialog(_attachment_table(row_count=2))
        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": _dialog(attachment_table=None),
                ".ui.download": FakeLocator(count=1, visible=True, enabled=True),
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=FakeDownload(),
        )

        def reopen_and_fix_dialog(_doc: MeetingDocument) -> _FakeSearchResult:
            page._locators["#formXuLy"] = dialog_with_table
            return _FakeSearchResult(success=True, found=True)

        vb_search_agent = _FakeVBSearchAgent()
        vb_search_agent.search = reopen_and_fix_dialog  # type: ignore[method-assign]

        progress: List[str] = []

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir), vb_search_agent)
            result = agent.download(document, progress_callback=progress.append)

        self.assertTrue(result.success)
        self.assertTrue(close_button_locator.clicked)
        self.assertEqual(
            progress,
            [
                "Attachment section missing.",
                "Closing dialog...",
                "Reopening document...",
                "Attachment section detected.",
                "Downloading...",
            ],
        )

        diagnostics = _read_diagnostics(document.number)
        self.assertTrue(diagnostics["reopened_dialog"])
        self.assertEqual(diagnostics["attachment_row_count"], 2)

    def test_still_incomplete_after_one_reopen_returns_original_error_no_second_reopen(self) -> None:
        """The exact production bug this refactor fixes: giving up after
        a still-incomplete reopen used to return WITHOUT ever closing
        the (reopened) dialog again, leaving it open to stall the next
        document's search — confirmed by a real multi-document E2E run.
        """

        document = MeetingDocument(number="TEST/CASE-STILL-INCOMPLETE")

        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": _dialog(attachment_table=None),
                "#formXuLy .close.icon:visible": close_button_locator,
            }
        )
        vb_search_agent = _FakeVBSearchAgent(results=[_FakeSearchResult(success=True, found=True)])

        progress: List[str] = []

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir), vb_search_agent)
            result = agent.download(document, progress_callback=progress.append)

        self.assertFalse(result.success)
        self.assertEqual(result.error, _INCOMPLETE_DIALOG_MESSAGE)
        # Reopened exactly once — search() called exactly once, not looped.
        self.assertEqual(vb_search_agent.calls, ["TEST/CASE-STILL-INCOMPLETE"])
        self.assertNotIn("Attachment section detected.", progress)
        self.assertNotIn("Downloading...", progress)
        # The dialog is still closed on the way out, even after giving up.
        self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertTrue(diagnostics["reopened_dialog"])

    def test_reopen_search_failure_returns_original_error_without_downloading(self) -> None:
        document = MeetingDocument(number="TEST/CASE-REOPEN-FAILS")

        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": _dialog(attachment_table=None),
                "#formXuLy .close.icon:visible": close_button_locator,
            }
        )
        vb_search_agent = _FakeVBSearchAgent(results=[_FakeSearchResult(success=True, found=False)])

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir), vb_search_agent)
            result = agent.download(document)

        self.assertFalse(result.success)
        self.assertEqual(result.error, _INCOMPLETE_DIALOG_MESSAGE)
        self.assertEqual(vb_search_agent.calls, ["TEST/CASE-REOPEN-FAILS"])
        self.assertTrue(close_button_locator.clicked)

    def test_download_control_not_visible_is_incomplete_and_triggers_reopen(self) -> None:
        document = MeetingDocument(number="TEST/CASE-CONTROL-NOT-VISIBLE")

        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": _dialog(_attachment_table(row_count=5)),
                ".ui.download": FakeLocator(count=1, visible=False, enabled=True),
                "#formXuLy .close.icon:visible": close_button_locator,
            }
        )
        vb_search_agent = _FakeVBSearchAgent(results=[_FakeSearchResult(success=True, found=True)])

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir), vb_search_agent)
            result = agent.download(document)

        # Reopened once, control still not visible on re-inspection (same
        # fake state) — fails cleanly, no infinite loop.
        self.assertFalse(result.success)
        self.assertEqual(vb_search_agent.calls, [document.number])
        self.assertTrue(close_button_locator.clicked)


class AdaptiveDownloadTimeoutTests(unittest.TestCase):
    """9047/TTr-SXD: VBĐH builds a ZIP archive before a multi-attachment
    download starts; a fixed 30s timeout was confirmed too short."""

    def test_compute_timeout_formula(self) -> None:
        self.assertEqual(DownloadAgent._compute_download_timeout_ms(0), 30_000)
        self.assertEqual(DownloadAgent._compute_download_timeout_ms(1), 35_000)
        self.assertEqual(DownloadAgent._compute_download_timeout_ms(14), 100_000)

    def test_compute_timeout_caps_at_maximum(self) -> None:
        # 30 + 5*30 = 180, capped to 120.
        self.assertEqual(
            DownloadAgent._compute_download_timeout_ms(30), _MAX_DOWNLOAD_TIMEOUT_SECONDS * 1000
        )
        # Right at the boundary: 30 + 5*18 = 120, exactly the cap.
        self.assertEqual(DownloadAgent._compute_download_timeout_ms(18), 120_000)

    def _build_page_for_row_count(
        self, row_count: int, control_locator: FakeLocator, close_button_locator: FakeLocator
    ) -> FakePage:
        dialog_locator = _dialog(_attachment_table(row_count=row_count))
        return FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=FakeDownload(),
        )

    def test_expect_download_receives_computed_timeout_for_many_attachments(self) -> None:
        """Reproduces 9047/TTr-SXD's shape (14 attachments) — confirms the
        computed 100s timeout (not the old fixed 30s) actually reaches
        page.expect_download()."""

        document = MeetingDocument(number="TEST/CASE-14-ATTACHMENTS")
        control_locator = FakeLocator(count=1, visible=True, enabled=True)
        close_button_locator = _close_button()
        page = self._build_page_for_row_count(14, control_locator, close_button_locator)

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

        self.assertTrue(result.success)
        self.assertEqual(page.last_expect_download_timeout_ms, 100_000)
        self.assertTrue(close_button_locator.clicked)

    def test_single_attachment_timeout_is_not_unnecessarily_slowed(self) -> None:
        """Regression: a single-attachment (the common case) download
        still gets essentially the original ~30s, not the 120s cap."""

        document = MeetingDocument(number="TEST/CASE-1-ATTACHMENT")
        control_locator = FakeLocator(count=1, visible=True, enabled=True)
        close_button_locator = _close_button()
        page = self._build_page_for_row_count(1, control_locator, close_button_locator)

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

        self.assertTrue(result.success)
        self.assertEqual(page.last_expect_download_timeout_ms, 35_000)
        self.assertTrue(close_button_locator.clicked)

    def test_timeout_reports_friendly_message_not_raw_playwright_error(self) -> None:
        document = MeetingDocument(number="TEST/CASE-ZIP-TIMEOUT")
        control_locator = FakeLocator(count=1, visible=True, enabled=True)
        dialog_locator = _dialog(_attachment_table(row_count=14))
        close_button_locator = _close_button()
        page = FakePage(
            locators={
                "#formXuLy": dialog_locator,
                ".ui.download": control_locator,
                "#formXuLy .close.icon:visible": close_button_locator,
            },
            download=None,
            raise_on_download_wait=PlaywrightTimeoutError(
                'Timeout 100000ms exceeded while waiting for event "download"'
            ),
        )

        with TemporaryDirectory() as tmp_dir:
            agent = DownloadAgent(FakeBrowserSession(page), Path(tmp_dir))
            result = agent.download(document)

        self.assertFalse(result.success)
        self.assertEqual(result.error, _DOWNLOAD_TIMEOUT_MESSAGE)
        self.assertNotIn("Playwright", result.error)
        self.assertNotIn("100000ms", result.error)
        self.assertTrue(close_button_locator.clicked)

        diagnostics = _read_diagnostics(document.number)
        self.assertEqual(diagnostics["error"], _DOWNLOAD_TIMEOUT_MESSAGE)
        self.assertEqual(diagnostics["attachment_row_count"], 14)
        # Even on timeout, the click was genuinely attempted with the
        # computed (not the old fixed) timeout.
        self.assertEqual(page.last_expect_download_timeout_ms, 100_000)


if __name__ == "__main__":
    unittest.main()
