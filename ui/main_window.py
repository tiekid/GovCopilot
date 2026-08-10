import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from config_store import set_config_value
from models.meeting import Meeting
from ui.analysis_worker import AnalysisWorker
from ui.gemini_test_worker import GeminiTestWorker
from ui.messages import GEMINI_NOT_CONFIGURED_MESSAGE
from ui.pipeline_worker import PipelineWorker
from ui.settings_dialog import SettingsDialog

_GEMINI_PROVIDERS = ("gemini", "auto")


def _format_analysis_summary(meeting: Meeting) -> str:
    """Format the concise AI analysis summary shown after "Phân tích".

    Presentation only — Meeting is already fully parsed by
    MeetingParserAgent (regex fields + AI-extracted documents); this
    function only decides how to display it.
    """

    time_line = " ".join(part for part in (meeting.meeting_date, meeting.meeting_time) if part)

    lines = [
        f"Cuộc họp: {meeting.meeting_name or '(không xác định)'}",
        f"Thời gian: {time_line or '(không xác định)'}",
        f"Địa điểm: {meeting.location or '(không xác định)'}",
        f"Số văn bản liên quan: {len(meeting.documents)}",
    ]

    if meeting.documents:
        lines.append("")
        lines.append("Danh sách số văn bản:")
        for document in meeting.documents:
            if document.title:
                lines.append(f"✓ {document.number}")
                lines.append(f"  {document.title}")
            else:
                lines.append(document.number)

    return "\n".join(lines)


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("GovCopilot v1.0")
        self.resize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        # ==========================
        # Chọn thư mời
        # ==========================

        layout.addWidget(QLabel("Thư mời họp"))

        row = QHBoxLayout()

        self.invitation_path = QLineEdit()
        self.invitation_path.setReadOnly(True)

        self.btn_choose = QPushButton("Chọn thư mời")

        row.addWidget(self.invitation_path)
        row.addWidget(self.btn_choose)

        layout.addLayout(row)

        # ==========================
        # Phân tích
        # ==========================

        self.btn_analyze = QPushButton("Phân tích")

        layout.addWidget(self.btn_analyze)

        # ==========================
        # Xem văn bản gốc (debug)
        # ==========================

        self.btn_show_raw = QPushButton("Xem văn bản gốc")
        self.btn_show_raw.setEnabled(False)

        layout.addWidget(self.btn_show_raw)

        # ==========================
        # Tải tài liệu
        # ==========================

        self.btn_download = QPushButton("Tải tài liệu")

        layout.addWidget(self.btn_download)

        # ==========================
        # Cài đặt
        # ==========================

        self.btn_settings = QPushButton("Cài đặt")

        layout.addWidget(self.btn_settings)

        # ==========================
        # Kết quả
        # ==========================

        layout.addWidget(QLabel("Nội dung thư mời"))

        self.result = QTextEdit()
        self.result.setReadOnly(True)

        layout.addWidget(self.result)

        # ==========================
        # Event
        # ==========================

        self.btn_choose.clicked.connect(self.choose_file)
        self.btn_analyze.clicked.connect(self.analyze)
        self.btn_show_raw.clicked.connect(self.show_raw_text)
        self.btn_download.clicked.connect(self.download_documents)
        self.btn_settings.clicked.connect(self.open_settings)

        self._pipeline_thread: QThread | None = None
        self._pipeline_worker: PipelineWorker | None = None

        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._last_raw_text: str | None = None

        self._startup_gemini_thread: QThread | None = None
        self._startup_gemini_worker: GeminiTestWorker | None = None

        # First-run experience: check configuration proactively. Only
        # calls Gemini if a key is already present and no model has
        # been selected yet (never for a missing key).
        self._check_provider_configuration()

    def choose_file(self) -> None:

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn thư mời",
            "",
            "Documents (*.pdf *.docx)"
        )

        if file_path:
            self.invitation_path.setText(file_path)

    def analyze(self) -> None:
        """Read the invitation, run AI extraction, and show a concise summary.

        Runs off the main thread (AnalysisWorker) since AI extraction
        is not instant — the window stays responsive while it runs.
        The raw invitation text is cached for "Xem văn bản gốc", never
        shown here by default.
        """

        file_path = self.invitation_path.text()

        if not file_path:
            self.result.setPlainText("Chưa chọn thư mời.")
            return

        self._set_buttons_enabled(False)
        self.result.clear()

        thread = QThread()
        worker = AnalysisWorker(file_path)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_analysis_progress)
        worker.finished.connect(self._on_analysis_finished)
        worker.failed.connect(self._on_analysis_failed)
        worker.configuration_error.connect(self._on_analysis_configuration_error)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.configuration_error.connect(thread.quit)
        thread.finished.connect(self._on_analysis_thread_finished)

        self._analysis_thread = thread
        self._analysis_worker = worker

        thread.start()

    def _on_analysis_progress(self, message: str) -> None:
        self.result.append(message)

    def _on_analysis_finished(self, meeting: Meeting, raw_text: str) -> None:
        self._last_raw_text = raw_text
        self.result.setPlainText(_format_analysis_summary(meeting))

    def _on_analysis_failed(self, message: str) -> None:
        self.result.setPlainText(f"Lỗi phân tích: {message}")

    def _on_analysis_configuration_error(self, _message: str) -> None:
        self.result.setPlainText(GEMINI_NOT_CONFIGURED_MESSAGE)

    def _on_analysis_thread_finished(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._set_buttons_enabled(True)

    def show_raw_text(self) -> None:
        """Debug-only action: display the last analyzed invitation's raw text."""

        if self._last_raw_text is None:
            self.result.setPlainText("Chưa có văn bản gốc. Vui lòng phân tích trước.")
            return

        self.result.setPlainText(self._last_raw_text)

    def download_documents(self) -> None:

        file_path = self.invitation_path.text()

        if not file_path:
            self.result.setPlainText("Chưa chọn thư mời.")
            return

        self._set_buttons_enabled(False)

        self.result.clear()

        thread = QThread()
        worker = PipelineWorker(file_path)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_pipeline_progress)
        worker.finished.connect(self._on_pipeline_finished)
        worker.failed.connect(self._on_pipeline_failed)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_pipeline_thread_finished)

        self._pipeline_thread = thread
        self._pipeline_worker = worker

        thread.start()

    def _on_pipeline_progress(self, message: str) -> None:
        self.result.append(message)

    def _on_pipeline_finished(self, meeting: Meeting) -> None:
        self.result.append(f"\nCuộc họp: {meeting.meeting_name}")

    def _on_pipeline_failed(self, message: str) -> None:
        self.result.append(f"\nLỗi: {message}")

    def _on_pipeline_thread_finished(self) -> None:
        self._pipeline_thread = None
        self._pipeline_worker = None
        self._set_buttons_enabled(True)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)

        if dialog.exec():
            self._check_provider_configuration()

    def _check_provider_configuration(self) -> None:
        """Proactively check Gemini configuration at startup / after Settings closes.

        Three outcomes, in order:
        - No API key: show the configuration message. Never calls Gemini.
        - Key present but no model selected yet: discover one in the
          background (this is the one case that does call Gemini).
        - Otherwise (Ollama-only, or Gemini already has a model): clear.
        """

        provider = config.AI_PROVIDER.strip().lower()

        if provider in _GEMINI_PROVIDERS and not config.GEMINI_API_KEY:
            self.result.setPlainText(GEMINI_NOT_CONFIGURED_MESSAGE)
            return

        if provider in _GEMINI_PROVIDERS and config.GEMINI_API_KEY and not config.GEMINI_MODEL:
            self._discover_gemini_model_in_background()
            return

        self.result.clear()

    def _discover_gemini_model_in_background(self) -> None:
        """Connect to Gemini, list models, select + persist the first text-capable one."""

        self.result.setPlainText("Đang chọn model Gemini...")

        thread = QThread()
        worker = GeminiTestWorker(config.GEMINI_API_KEY)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_startup_gemini_model_selected)
        worker.failed.connect(self._on_startup_gemini_model_selection_failed)

        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_startup_gemini_thread_finished)

        self._startup_gemini_thread = thread
        self._startup_gemini_worker = worker

        thread.start()

    def _on_startup_gemini_model_selected(self, model: str) -> None:
        set_config_value("GEMINI_MODEL", model)
        self.result.setPlainText(f"Đã chọn model Gemini: {model}")

    def _on_startup_gemini_model_selection_failed(self, message: str) -> None:
        self.result.setPlainText(message)

    def _on_startup_gemini_thread_finished(self) -> None:
        self._startup_gemini_thread = None
        self._startup_gemini_worker = None

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_choose.setEnabled(enabled)
        self.btn_analyze.setEnabled(enabled)
        self.btn_download.setEnabled(enabled)
        self.btn_settings.setEnabled(enabled)
        self.btn_show_raw.setEnabled(enabled and self._last_raw_text is not None)


def run() -> None:

    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
