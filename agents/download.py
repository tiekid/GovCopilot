"""Agent that downloads the attachment for an already-opened VBĐH document.

Assumes VBSearchAgent has already located and opened a matching
document (the #formXuLy modal) on the shared browser session. This
agent only downloads the attachment for that already-open document —
it never searches, reopens the modal, navigates, or performs AI
analysis. It is a single-document component; batch orchestration
belongs to the caller.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from browser.login import BrowserSession
from models.document import MeetingDocument

logger = logging.getLogger(__name__)

_DOWNLOAD_BUTTON_SELECTOR = ".ui.download"


@dataclass
class DownloadResult:
    """Outcome of downloading the attachment for one MeetingDocument."""

    document: MeetingDocument
    success: bool
    local_path: Optional[str] = None
    error: Optional[str] = None


class DownloadAgent:
    """Downloads the attachment for an already-opened VBĐH document.

    Never searches, never reopens the modal, never navigates, never
    inspects #formXuLy beyond clicking the download control, and never
    performs AI analysis.
    """

    def __init__(self, browser_session: BrowserSession, download_dir: Path) -> None:
        self._browser_session = browser_session
        self._download_dir = download_dir

    def download(self, document: MeetingDocument) -> DownloadResult:

        page = self._browser_session.get_page()

        logger.info("Downloading attachment for document number %s", document.number)

        try:
            self._download_dir.mkdir(parents=True, exist_ok=True)

            with page.expect_download() as download_info:
                page.locator(_DOWNLOAD_BUTTON_SELECTOR).click()

            download = download_info.value

            saved_path = self._download_dir / download.suggested_filename
            download.save_as(saved_path)

            document.downloaded = True
            document.local_path = str(saved_path)

            logger.info("Saved document number %s to %s", document.number, saved_path)

            return DownloadResult(
                document=document,
                success=True,
                local_path=str(saved_path),
                error=None,
            )

        except Exception as exc:
            logger.exception("Download failed for document number %s", document.number)
            return DownloadResult(
                document=document,
                success=False,
                local_path=None,
                error=str(exc),
            )
