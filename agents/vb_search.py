"""Agent that searches VBĐH for each MeetingDocument and opens a match.

Navigates to the VBĐH search page, submits a search for each document
number, and — using a verified generic result-cell selector — locates
and opens the matching result. All selectors below are verified via
Playwright Codegen against the real VBĐH system; none are guessed.

Read-only: opening a match reveals the `#formXuLy` modal, but this
agent never interacts with it further, never downloads, and never
performs AI analysis. That is out of scope for VBSearchAgent.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

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
    """Searches VBĐH for each MeetingDocument and opens a matching result.

    Never downloads, never performs AI analysis, and never interacts
    with the `#formXuLy` modal beyond the click that opens it.
    """

    def __init__(self, browser_session: BrowserSession) -> None:
        self._browser_session = browser_session

    def search(self, documents: List[MeetingDocument]) -> List[VBSearchResult]:

        results: List[VBSearchResult] = []

        for document in documents:
            results.append(self._search_one(document))

        logger.info(
            "VBĐH search complete: %d succeeded, %d found, %d failed",
            sum(1 for r in results if r.success),
            sum(1 for r in results if r.found),
            sum(1 for r in results if not r.success),
        )

        return results

    def _search_one(self, document: MeetingDocument) -> VBSearchResult:

        page = self._browser_session.get_page()

        logger.info("Submitting VBĐH search for document number %s", document.number)

        try:
            self._navigate_to_search_page(page)

            page.get_by_role("textbox", name=_NUMBER_FIELD_ROLE_NAME).fill(document.number)
            page.locator(_SEARCH_FORM_SELECTOR).get_by_text(_SEARCH_SUBMIT_TEXT).click()

            page.wait_for_load_state("networkidle")

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
