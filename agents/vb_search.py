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
"""

import logging
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page

from browser.login import BrowserSession
from models.document import MeetingDocument

logger = logging.getLogger(__name__)

# Verified via Playwright Codegen against the real VBĐH system.
_LOGIN_URL = "https://vbdh.tayninh.gov.vn/dang-nhap"
_MENU_MANAGEMENT_TEXT = "Quản lý VB&ĐH"
_MENU_SEARCH_TEXT = "Tìm kiếm 0"
_MENU_INCOMING_DOCS_LINK_NAME = " Văn bản đến"  # leading space verified in the recording
_NUMBER_FIELD_ROLE_NAME = "Nhập số, ký hiệu"
_SEARCH_FORM_SELECTOR = "#formTimKiem"
_SEARCH_SUBMIT_TEXT = "Tìm kiếm"

# Verified generic result-cell selector (Codegen recording covering two
# distinct documents — confirmed not tied to any one document's text).
_RESULT_CELL_SELECTOR = 'td.so-hieu[ng-click="$p.showFormXuLyClick(item)"]'

# Verified against the real VBĐH system (network instrumentation): the
# actual search API request/response, confirmed to resolve correctly
# whether the search returns 0 or N results — unlike any DOM signal,
# which was confirmed to render nothing at all for a zero-result search.
_SEARCH_RESPONSE_URL_SUBSTRING = "GetVanBansByPage"
_SEARCH_RESPONSE_TIMEOUT_MS = 15_000


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

            self._submit_search(page, document)

            found = self._open_matching_result(page, document)

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
        recorded menu-click sequence.
        """

        page.goto(_LOGIN_URL)
        page.get_by_text(_MENU_MANAGEMENT_TEXT).click()
        page.get_by_text(_MENU_SEARCH_TEXT).click()
        page.get_by_role("link", name=_MENU_INCOMING_DOCS_LINK_NAME).click()

    def _submit_search(self, page: Page, document: MeetingDocument) -> None:
        """Fill and submit the search, waiting for the actual search API response.

        Uses page.expect_response() around the submit click to wait for
        the real search request/response round-trip, not a DOM guess —
        verified against the real system to resolve correctly whether
        the search returns 0 or N results. A non-200 response, or the
        response never arriving within the timeout, is treated as a
        search failure (raised here, becomes success=False), not "not
        found".
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

    def _open_matching_result(self, page: Page, document: MeetingDocument) -> bool:
        """Locate the result cell exactly matching ``document.number`` and click it.

        Comparison ignores whitespace/line breaks; the first exact match
        is clicked. Clicking opens the `#formXuLy` modal, which this
        agent does not otherwise interact with.
        """

        cells = page.locator(_RESULT_CELL_SELECTOR)
        target = self._normalize(document.number)

        for index in range(cells.count()):
            cell = cells.nth(index)

            if self._normalize(cell.inner_text()) == target:
                cell.click()
                return True

        return False

    @staticmethod
    def _normalize(text: str) -> str:
        """Strip all whitespace/line breaks for exact, whitespace-insensitive comparison."""

        return "".join(text.split())
