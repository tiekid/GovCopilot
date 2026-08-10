"""Background worker that reads + AI-parses one invitation off the Qt main thread.

Constructs the existing MeetingParserAgent and calls its parse()
method — nothing here duplicates any agent's logic, and no extraction
logic lives here. Kept separate from PipelineWorker
(ui/pipeline_worker.py) because analysis never touches the browser: it
only reads the invitation and runs AI extraction, so it doesn't need a
BrowserSession.
"""

import logging

from PySide6.QtCore import QObject, Signal

from agents.meeting_parser import MeetingParserAgent
from parser.invitation_reader import read_invitation
from providers.ai_provider import ProviderConfigurationError
from providers.gemini_provider import GeminiProviderError
from ui.messages import GEMINI_UNAVAILABLE_MESSAGE

logger = logging.getLogger(__name__)


class AnalysisWorker(QObject):
    """Reads and parses one invitation (AI-backed), off the main thread.

    Emits `progress` with a short status message at each stage, then
    `finished` with (Meeting, raw_text) on success. On failure, emits
    `configuration_error` specifically when the selected AI provider
    isn't usably configured yet (e.g. no Gemini API key) — a "go set
    this up" state, distinct from `failed`, which covers everything
    else (a bad file, a network hiccup, ...).

    MeetingParserAgent (and therefore AIInvitationExtractor/AIProvider
    selection) is constructed inside run(), not __init__ — provider
    selection can itself raise ProviderConfigurationError, and it must
    do so on the worker thread, inside this try/except, not synchronously
    while MainWindow is still constructing the worker.

    MeetingParserAgent.parse() itself has no progress hook (adding one
    is an extraction-layer change, out of scope here), so "Parsing AI
    response..." / "Building summary..." are reported as a best-effort
    sequence around that one call rather than genuine sub-step
    telemetry — "Calling AI..." is the one stage that does span the
    real, multi-second work.
    """

    progress = Signal(str)
    finished = Signal(object, str)
    failed = Signal(str)
    configuration_error = Signal(str)

    def __init__(self, invitation_path: str) -> None:
        super().__init__()
        self._invitation_path = invitation_path

    def run(self) -> None:

        try:
            self.progress.emit("Reading invitation...")
            text = read_invitation(self._invitation_path)

            self.progress.emit("Calling AI...")
            meeting_parser = MeetingParserAgent()
            meeting = meeting_parser.parse(text)

            self.progress.emit("Parsing AI response...")
            self.progress.emit("Building summary...")

            self.finished.emit(meeting, text)

        except ProviderConfigurationError as exc:
            logger.warning("AI provider not configured: %s", exc)
            self.configuration_error.emit(str(exc))

        except GeminiProviderError as exc:
            logger.warning("Gemini request failed: %s", exc)
            self.failed.emit(GEMINI_UNAVAILABLE_MESSAGE)

        except Exception as exc:
            logger.exception("Analysis worker failed")
            self.failed.emit(str(exc))
