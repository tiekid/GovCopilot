"""Minimal Settings dialog for configuring the AI provider.

Presentation only: reads current values from config.py, writes changed
values to .env via config_store.set_config_value() (the project's
existing configuration convention — config.py already loads .env; no
separate config.json mechanism is introduced), which also updates the
in-process config module directly so settings take effect on the very
next provider construction, without an app restart.

"Kiểm tra kết nối" (Test connection) only fills in the discovered
Gemini model — it does not persist anything by itself. Persistence
happens only via Save, so Cancel after a test still discards it, same
as every other field in this dialog.
"""

from typing import Optional

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from config_store import set_config_value
from ui.gemini_test_worker import GeminiTestWorker

_PROVIDER_GEMINI = "gemini"
_PROVIDER_OLLAMA = "ollama"


class SettingsDialog(QDialog):
    """AI provider settings: Gemini (API Key + Model) or Ollama (URL + Model)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Cài đặt")

        layout = QVBoxLayout(self)

        provider_form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Gemini", _PROVIDER_GEMINI)
        self.provider_combo.addItem("Ollama", _PROVIDER_OLLAMA)
        provider_form.addRow("AI Provider", self.provider_combo)
        layout.addLayout(provider_form)

        self.stack = QStackedWidget()

        self.gemini_page = QWidget()
        gemini_layout = QVBoxLayout(self.gemini_page)
        gemini_form = QFormLayout()
        self.gemini_api_key = QLineEdit()
        self.gemini_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_model = QLineEdit()
        self.gemini_model.setPlaceholderText("(tự động chọn nếu để trống)")
        gemini_form.addRow("API Key", self.gemini_api_key)
        gemini_form.addRow("Model", self.gemini_model)
        gemini_layout.addLayout(gemini_form)

        self.btn_test_connection = QPushButton("Kiểm tra kết nối")
        gemini_layout.addWidget(self.btn_test_connection)

        self.gemini_status_label = QLabel("")
        self.gemini_status_label.setWordWrap(True)
        gemini_layout.addWidget(self.gemini_status_label)

        self.stack.addWidget(self.gemini_page)

        self.ollama_page = QWidget()
        ollama_form = QFormLayout(self.ollama_page)
        self.ollama_url = QLineEdit()
        self.ollama_model = QLineEdit()
        ollama_form.addRow("URL", self.ollama_url)
        ollama_form.addRow("Model", self.ollama_model)
        self.stack.addWidget(self.ollama_page)

        layout.addWidget(self.stack)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.btn_test_connection.clicked.connect(self._test_connection)

        self._test_thread: Optional[QThread] = None
        self._test_worker: Optional[GeminiTestWorker] = None

        self._load_current_values()

    def _load_current_values(self) -> None:

        index = self.provider_combo.findData(config.AI_PROVIDER)
        self.provider_combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_provider_changed()

        self.gemini_api_key.setText(config.GEMINI_API_KEY)
        self.gemini_model.setText(config.GEMINI_MODEL)
        self.ollama_url.setText(config.OLLAMA_URL)
        self.ollama_model.setText(config.OLLAMA_MODEL)

    def _on_provider_changed(self) -> None:

        provider = self.provider_combo.currentData()
        page = self.gemini_page if provider == _PROVIDER_GEMINI else self.ollama_page
        self.stack.setCurrentWidget(page)

    def _test_connection(self) -> None:

        api_key = self.gemini_api_key.text().strip()

        self.btn_test_connection.setEnabled(False)
        self.gemini_status_label.setText("Đang kiểm tra kết nối...")

        thread = QThread()
        worker = GeminiTestWorker(api_key)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_test_connection_succeeded)
        worker.failed.connect(self._on_test_connection_failed)

        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_test_connection_thread_finished)

        self._test_thread = thread
        self._test_worker = worker

        thread.start()

    def _on_test_connection_succeeded(self, model: str) -> None:
        self.gemini_model.setText(model)
        self.gemini_status_label.setText(f"✓ Kết nối thành công. Model: {model}")

    def _on_test_connection_failed(self, message: str) -> None:
        self.gemini_status_label.setText(message)

    def _on_test_connection_thread_finished(self) -> None:
        self._test_thread = None
        self._test_worker = None
        self.btn_test_connection.setEnabled(True)

    def _save(self) -> None:

        values = {
            "AI_PROVIDER": self.provider_combo.currentData(),
            "GEMINI_API_KEY": self.gemini_api_key.text().strip(),
            "GEMINI_MODEL": self.gemini_model.text().strip(),
            "OLLAMA_URL": self.ollama_url.text().strip() or config.OLLAMA_URL,
            "OLLAMA_MODEL": self.ollama_model.text().strip() or config.OLLAMA_MODEL,
        }

        for key, value in values.items():
            set_config_value(key, value)

        self.accept()
