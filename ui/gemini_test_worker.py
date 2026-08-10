"""Background worker that verifies Gemini connectivity and selects a model.

Connects to Gemini, lists available models, and picks the first one
that supports text generation — off the Qt main thread, since it's a
real network call. Used both by Settings > "Kiểm tra kết nối" and by
MainWindow's startup check. Never surfaces a raw SDK/API exception:
only a friendly message.
"""

import logging

from PySide6.QtCore import QObject, Signal

from providers.ai_provider import ProviderConfigurationError
from providers.gemini_provider import GeminiProviderError, select_first_text_generation_model

logger = logging.getLogger(__name__)


class GeminiTestWorker(QObject):
    """Emits `succeeded` with the selected model name, or `failed` with a friendly message."""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    def run(self) -> None:

        try:
            model = select_first_text_generation_model(self._api_key)
            self.succeeded.emit(model)

        except ProviderConfigurationError:
            logger.warning("Gemini test connection: API key missing")
            self.failed.emit("Chưa nhập Gemini API Key.")

        except GeminiProviderError as exc:
            logger.warning("Gemini test connection failed: %s", exc)
            self.failed.emit(
                "Không thể kết nối tới Google Gemini. Vui lòng kiểm tra API Key và thử lại."
            )

        except Exception:
            logger.exception("Gemini test connection failed unexpectedly")
            self.failed.emit("Không thể kết nối tới Google Gemini. Vui lòng thử lại sau.")
