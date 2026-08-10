"""Agent that searches VBĐH for a single MeetingDocument and opens a match.

Navigates to the VBĐH search page, submits a search for the document
number, and — using a verified generic result-cell selector — locates
and opens the matching result. All selectors below are verified via
Playwright Codegen against the real VBĐH system; none are guessed.

Read-only: opening a match reveals the `#formXuLy` modal, but this
agent never interacts with it further, never downloads, and never
performs AI analysis. That is out of scope for VBSearchAgent. Batch
orchestration across multiple documents belongs to the caller, not
this agent.

Opening a result row waits _SEARCH_RESULT_SETTLE_DELAY_MS after the
row becomes visible before clicking it — a live-evidence-justified
exception to the project's no-fixed-delay rule, see that constant's
comment for the investigation this is based on.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Locator, Page

from browser.login import BrowserSession
from models.document import MeetingDocument

logger = logging.getLogger(__name__)

# Investigation instrumentation (Bug 2): 8069/TTr-SYT and 9949/BC-STC
# were reported "No matching VBĐH result" despite the user confirming
# both exist. Before concluding "not found", capture every observable
# signal that could explain a false negative — same evidence-first
# pattern as agents/download.py's DownloadDiagnostics.
_SEARCH_DIAGNOSTICS_LOG_DIR = Path("logs") / "search"

# Verified via Playwright Codegen against the real VBĐH system.
_LOGIN_URL = "https://vbdh.tayninh.gov.vn/dang-nhap"
_MENU_MANAGEMENT_TEXT = "Quản lý VB&ĐH"
_MENU_SEARCH_TEXT = "Tìm kiếm 0"
_MENU_INCOMING_DOCS_LINK_NAME = " Văn bản đến"  # leading space verified in the recording
_NUMBER_FIELD_ROLE_NAME = "Nhập số, ký hiệu"
_SEARCH_FORM_SELECTOR = "#formTimKiem"
_SEARCH_SUBMIT_TEXT = "Tìm kiếm"

# Verified real URL (captured in logs/download/*.json's url_before_click
# for every real document searched this session) — used to detect
# "we're already on the search page" so a later search() call in the
# same batch never re-navigates to _LOGIN_URL needlessly. Re-navigating
# there every time relies on VBĐH's own redirect-if-authenticated
# behavior, which raced against that redirect when it happened once per
# document in a multi-document batch (see docs/09_LESSONS_LEARNED.md).
_SEARCH_PAGE_URL_SUBSTRING = "/van-ban/tim-kiem/van-ban-den"

# Verified generic result-cell selector (Codegen recording covering two
# distinct documents — confirmed not tied to any one document's text).
_RESULT_CELL_SELECTOR = 'td.so-hieu[ng-click="$p.showFormXuLyClick(item)"]'

# Verified against the real VBĐH system (network instrumentation): the
# actual search API request/response, confirmed to resolve correctly
# whether the search returns 0 or N results — unlike any DOM signal,
# which was confirmed to render nothing at all for a zero-result search.
_SEARCH_RESPONSE_URL_SUBSTRING = "GetVanBansByPage"
_SEARCH_RESPONSE_TIMEOUT_MS = 15_000

# Deliberate, evidence-based exception to "no fixed delays" (see
# docs/06_PLAYWRIGHT.md): VBĐH has a client-side race where clicking a
# result row immediately after it becomes visible sometimes opens the
# detail dialog with its attachment items bound as undefined (a
# one-shot internal cache lookup that never re-runs — confirmed via
# direct AngularJS scope inspection, not a rendering lag: no DOM
# mutation, network response, or Angular digest signal exists to wait
# on instead — all were investigated and ruled out live). A live
# investigation of 80 clean attempts (20 per delay, fresh browser
# session each) found:
#   150 ms = 18/20 (90%)
#   200 ms = 20/20 (100%)
#   250 ms = 20/20 (100%)
#   300 ms = 20/20 (100%)
# 200ms is statistically indistinguishable from 250/300ms (Fisher's
# exact p=1.0) and is the smallest delay that consistently avoided the
# race — so it's used here rather than a larger, unjustified margin.
_SEARCH_RESULT_SETTLE_DELAY_MS = 200


@dataclass
class VBSearchResult:
    """Outcome of submitting a VBĐH search for one MeetingDocument.

    ``detail_url`` is always ``None`` this sprint: opening a match reveals
    the ``#formXuLy`` modal rather than navigating to a detail page, so
    there is no URL to capture. The field is kept (rather than removed)
    so the public API doesn't change again once a detail-page workflow
    exists.
    """

    document: MeetingDocument
    success: bool
    found: bool
    detail_url: Optional[str] = None
    error: Optional[str] = None


class VBSearchAgent:
    """Searches VBĐH for one MeetingDocument and opens a matching result.

    Single-document component: batch orchestration across multiple
    documents belongs to the caller. Never downloads, never performs AI
    analysis, and never interacts with the `#formXuLy` modal beyond the
    click that opens it.
    """

    def __init__(self, browser_session: BrowserSession) -> None:
        self._browser_session = browser_session

    def search(self, document: MeetingDocument) -> VBSearchResult:

        page = self._browser_session.get_page()

        logger.info("Submitting VBĐH search for document number %s", document.number)

        try:
            self._navigate_to_search_page(page)

            response_status = self._submit_search(page, document)

            found = self._open_matching_result(page, document, response_status)

            if found:
                logger.info("Opened matching VBĐH result for document number %s", document.number)
            else:
                logger.warning("No matching VBĐH result for document number %s", document.number)

            return VBSearchResult(document=document, success=True, found=found)

        except Exception as exc:
            logger.exception("VBĐH search failed for document number %s", document.number)
            return VBSearchResult(document=document, success=False, found=False, error=str(exc))

    def _navigate_to_search_page(self, page: Page) -> None:
        """Reach the incoming-documents search page via the verified menu path.

        No verified direct URL to the search page exists — only this
        recorded menu-click sequence. Skipped entirely if already on
        the search page (e.g. the 2nd+ document in a batch): navigating
        to _LOGIN_URL again once authentication has already succeeded
        is both unnecessary and races VBĐH's own redirect-away-from-
        login behavior — never call goto(_LOGIN_URL) once authenticated.
        """

        if _SEARCH_PAGE_URL_SUBSTRING in page.url:
            return

        page.goto(_LOGIN_URL)
        page.get_by_text(_MENU_MANAGEMENT_TEXT).click()
        page.get_by_text(_MENU_SEARCH_TEXT).click()
        page.get_by_role("link", name=_MENU_INCOMING_DOCS_LINK_NAME).click()

    def _submit_search(self, page: Page, document: MeetingDocument) -> int:
        """Fill and submit the search, waiting for the actual search API response.

        Uses page.expect_response() around the submit click to wait for
        the real search request/response round-trip, not a DOM guess —
        verified against the real system to resolve correctly whether
        the search returns 0 or N results. A non-200 response, or the
        response never arriving within the timeout, is treated as a
        search failure (raised here, becomes success=False), not "not
        found". Returns the response status, so the caller can log it
        even on a 200 that still turns up no matching row.
        """

        page.get_by_role("textbox", name=_NUMBER_FIELD_ROLE_NAME).fill(document.number)

        with page.expect_response(
            lambda response: _SEARCH_RESPONSE_URL_SUBSTRING in response.url,
            timeout=_SEARCH_RESPONSE_TIMEOUT_MS,
        ) as response_info:
            page.locator(_SEARCH_FORM_SELECTOR).get_by_text(_SEARCH_SUBMIT_TEXT).click()

        response = response_info.value

        if response.status != 200:
            raise RuntimeError(f"VBĐH search request failed with HTTP {response.status}")

        return response.status

    def _open_matching_result(
        self, page: Page, document: MeetingDocument, response_status: int
    ) -> bool:
        """Locate the result cell exactly matching ``document.number`` and click it.

        Compares only the document-number field — the cell's first
        line — never the whole cell text. Confirmed by real diagnostics
        (Bug 2): VBĐH appends an urgency annotation ("HỎA TỐC", "HỎA
        TỐC HẸN GIỜ", ...) on a second line within the same cell, so
        normalizing and comparing the whole multi-line cell text never
        matches a bare document number even when the row is right
        there. The first exact match is clicked. Clicking opens the
        `#formXuLy` modal, which this agent does not otherwise interact
        with. Before reporting "no match", every observable signal is
        logged — see _log_no_match_diagnostics.
        """

        cells = page.locator(_RESULT_CELL_SELECTOR)
        target = self._normalize(document.number)
        row_count = cells.count()

        for index in range(row_count):
            cell = cells.nth(index)

            # cell.inner_text() (below) already waits for the cell to
            # be visible, so by the time a match is found both the
            # results grid and the target row are confirmed visible —
            # exactly the point _SEARCH_RESULT_SETTLE_DELAY_MS is
            # meant to wait from, before clicking.
            if self._normalize(self._document_number_field(cell.inner_text())) == target:
                cell.wait_for(state="visible", timeout=_SEARCH_RESPONSE_TIMEOUT_MS)
                page.wait_for_timeout(_SEARCH_RESULT_SETTLE_DELAY_MS)
                cell.click()
                return True

        self._log_no_match_diagnostics(cells, document, target, row_count, response_status)

        return False

    def _log_no_match_diagnostics(
        self,
        cells: Locator,
        document: MeetingDocument,
        target: str,
        row_count: int,
        response_status: int,
    ) -> None:
        """Capture every observable signal before reporting "no matching result".

        Investigation-only: never changes the outcome, only records why
        it happened, so the real cause (pagination, a formatting
        mismatch, a stale/empty DOM, ...) can be diagnosed from
        evidence — same pattern as agents/download.py's
        DownloadDiagnostics — instead of guessed at.
        """

        try:
            visible_row_texts = [cells.nth(i).inner_text() for i in range(row_count)]
        except Exception:
            visible_row_texts = []

        diagnostics = {
            "document_number": document.number,
            "search_keyword": target,
            "row_count": row_count,
            "visible_row_count": len(visible_row_texts),
            "first_visible_row_text": visible_row_texts[0] if visible_row_texts else None,
            "visible_row_texts": visible_row_texts,
            "selector_used": _RESULT_CELL_SELECTOR,
            "network_response_status": response_status,
        }

        logger.warning(
            "No matching VBĐH result for document number %s — diagnostics: %s",
            document.number,
            diagnostics,
        )

        try:
            _SEARCH_DIAGNOSTICS_LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = _SEARCH_DIAGNOSTICS_LOG_DIR / f"{self._sanitize_filename(document.number)}.json"
            log_path.write_text(
                json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            logger.warning("Failed to save search diagnostics (non-fatal)", exc_info=True)

    @staticmethod
    def _document_number_field(cell_text: str) -> str:
        """Return only the document-number field from a result cell's text.

        The cell's first line is the document number; VBĐH appends an
        urgency annotation ("HỎA TỐC", "HỎA TỐC HẸN GIỜ", ...) on a
        following line within the *same* cell (confirmed by real
        diagnostics — Bug 2). Only the first line is ever the document
        number, never the whole cell text.
        """

        lines = cell_text.splitlines()

        return lines[0] if lines else ""

    @staticmethod
    def _normalize(text: str) -> str:
        """Strip all whitespace/line breaks for exact, whitespace-insensitive comparison."""

        return "".join(text.split())

    @staticmethod
    def _sanitize_filename(document_number: str) -> str:
        """Replace filesystem-unsafe characters (document numbers contain '/')."""

        sanitized = re.sub(r'[\\/:*?"<>|]', "_", document_number).strip()

        return sanitized or "unknown"
