"""Agent that submits a VBĐH document-number search for each MeetingDocument.

Scope for this sprint: navigate to the search page, fill the verified
search field, submit the search, and wait for the request to complete.
It reports only whether the search operation itself succeeded — it does
not inspect results, determine whether a document was found, open any
result, or download anything. All selectors below are verified via
Playwright Codegen against the real VBĐH system; none are guessed.
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


@dataclass
class VBSearchResult:
    """Outcome of submitting a VBĐH search for one MeetingDocument.

    ``success`` means only that the search operation completed without
    error. It does not indicate whether a matching document was found —
    that requires inspecting results, which is deferred to a later
    sprint pending a verified generic result-row selector.
    """

    document: MeetingDocument
    success: bool
    detail_url: Optional[str] = None
    error: Optional[str] = None


class VBSearchAgent:
    """Submits a VBĐH document-number search for each MeetingDocument.

    Read-only and search-only: navigates to the search page, fills and
    submits the search form, and waits for the request to complete.
    Never inspects results, opens a document, or downloads anything.
    """

    def __init__(self, browser_session: BrowserSession) -> None:
        self._browser_session = browser_session

    def search(self, documents: List[MeetingDocument]) -> List[VBSearchResult]:

        results: List[VBSearchResult] = []

        for document in documents:
            results.append(self._search_one(document))

        logger.info(
            "VBĐH search requests complete: %d succeeded, %d failed",
            sum(1 for r in results if r.success),
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

            logger.info("VBĐH search request completed for document number %s", document.number)

            return VBSearchResult(document=document, success=True)

        except Exception as exc:
            logger.exception("VBĐH search request failed for document number %s", document.number)
            return VBSearchResult(document=document, success=False, error=str(exc))

    def _navigate_to_search_page(self, page: Page) -> None:
        """Reach the incoming-documents search page via the verified menu path.

        No verified direct URL to the search page exists — only this
        recorded menu-click sequence.
        """

        page.goto(_LOGIN_URL)
        page.get_by_text(_MENU_MANAGEMENT_TEXT).click()
        page.get_by_text(_MENU_SEARCH_TEXT).click()
        page.get_by_role("link", name=_MENU_INCOMING_DOCS_LINK_NAME).click()
