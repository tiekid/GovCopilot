"""Background worker that runs DocumentPipeline off the Qt main thread.

Constructs the existing agents and BrowserSession, then drives
DocumentPipeline — nothing here duplicates any agent's orchestration
logic. Intended to be moved to a QThread so the GUI stays responsive.

Bug 1 fix: invitation parsing (agents.meeting_parser.MeetingParserAgent
— includes the AI extraction call, measured several to tens of
seconds) used to run *after* the browser opened and login was
confirmed, so the user saw "Đã đăng nhập." and then a long silent gap
before the first search — that gap was the AI call, not a wait.
Parsing doesn't touch the browser at all, so it now runs first; by the
time login is confirmed, the document list is already known and the
first search starts immediately. See docs/09_LESSONS_LEARNED.md.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from agents.download import DownloadAgent
from agents.meeting_parser import MeetingParserAgent
from agents.normalization import NormalizationAgent
from agents.vb_search import VBSearchAgent
from browser.login import BrowserSession, SessionState
from pipeline.document_pipeline import DocumentPipeline
from providers.ai_provider import ProviderConfigurationError
from providers.gemini_provider import GeminiProviderError
from ui.messages import GEMINI_NOT_CONFIGURED_MESSAGE, GEMINI_UNAVAILABLE_MESSAGE

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = _PROJECT_ROOT / "documents"
NORMALIZED_DIR = DOWNLOAD_DIR / "normalized"


class PipelineWorker(QObject):
    """Runs DocumentPipeline for one invitation, reporting progress via signals.

    Emits `progress` for each pipeline progress line, `finished` with the
    resulting Meeting on success, and `failed` with an error message if
    the run could not complete.
    """

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, invitation_path: str, download_dir: Path = DOWNLOAD_DIR) -> None:
        super().__init__()
        self._invitation_path = invitation_path
        self._download_dir = download_dir

    def run(self) -> None:

        browser_session: Optional[BrowserSession] = None

        try:
            meeting_parser = MeetingParserAgent()

            # Parse first — this is where the AI call happens, and it
            # doesn't need the browser at all. Doing it before opening
            # the browser/waiting for login means that wait is no
            # longer hidden behind an unrelated, unreported delay.
            meeting = DocumentPipeline(meeting_parser=meeting_parser).parse(
                self._invitation_path, progress_callback=self.progress.emit
            )

            self.progress.emit("Opening VBĐH...")

            browser_session = BrowserSession()

            _, state = browser_session.open()

            self.progress.emit("Checking session...")

            if state is SessionState.LOGIN_REQUIRED:
                # BrowserSession.open() already tried automatic login
                # (browser's own saved credentials) internally — still
                # LOGIN_REQUIRED here means that didn't work (e.g. no
                # saved credentials), so fall back to a manual login in
                # the visible browser window, same as before.
                self.progress.emit(
                    "Vui lòng đăng nhập trong cửa sổ trình duyệt đang mở. "
                    "Hệ thống sẽ tự động tiếp tục sau khi đăng nhập thành công..."
                )
                browser_session.wait_until_authenticated()

            t0 = time.perf_counter()
            self.progress.emit("Session valid.")
            logger.info("+%.1f Login detected", 0.0)

            vb_search_agent = VBSearchAgent(browser_session)
            # vb_search_agent passed through so DownloadAgent can reopen
            # the same document once if the attachment section doesn't
            # render on the first open — see docs/09_LESSONS_LEARNED.md.
            download_agent = DownloadAgent(browser_session, self._download_dir, vb_search_agent)
            normalization_agent = NormalizationAgent(output_dir=NORMALIZED_DIR)

            logger.info("+%.1f Session verified", time.perf_counter() - t0)

            first_search_logged = False

            def report_with_timing(message: str) -> None:
                nonlocal first_search_logged
                if not first_search_logged and message.startswith("Searching document:"):
                    logger.info("+%.1f First search begins (%s)", time.perf_counter() - t0, message)
                    first_search_logged = True
                self.progress.emit(message)

            pipeline = DocumentPipeline(
                meeting_parser=meeting_parser,
                vb_search_agent=vb_search_agent,
                download_agent=download_agent,
                normalization_agent=normalization_agent,
            )

            meeting = pipeline.process_documents(meeting, progress_callback=report_with_timing)

            # Return value (List[NormalizedAgendaGroup]) isn't consumed
            # yet — no ReviewAgent exists to receive it. finished still
            # carries the Meeting object, unchanged.
            pipeline.normalize_documents(meeting, progress_callback=report_with_timing)

            self.finished.emit(meeting)

        except ProviderConfigurationError as exc:
            logger.warning("AI provider not configured: %s", exc)
            self.failed.emit(GEMINI_NOT_CONFIGURED_MESSAGE)

        except GeminiProviderError as exc:
            logger.warning("Gemini request failed: %s", exc)
            self.failed.emit(GEMINI_UNAVAILABLE_MESSAGE)

        except Exception as exc:
            logger.exception("Pipeline worker failed")
            self.failed.emit(str(exc))

        finally:
            if browser_session is not None:
                browser_session.close()
