import sys

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

from parser.invitation_reader import read_invitation


class MainWindow(QMainWindow):

    def __init__(self):
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

    def choose_file(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn thư mời",
            "",
            "Documents (*.pdf *.docx)"
        )

        if file_path:
            self.invitation_path.setText(file_path)

    def analyze(self):

        file_path = self.invitation_path.text()

        if not file_path:
            self.result.setPlainText("Chưa chọn thư mời.")
            return

        try:

            text = read_invitation(file_path)

            self.result.setPlainText(text)

        except Exception as ex:

            self.result.setPlainText(str(ex))


def run():

    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())