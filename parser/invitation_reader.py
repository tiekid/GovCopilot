from pathlib import Path

from pypdf import PdfReader
from docx import Document


def read_invitation(file_path: str) -> str:
    path = Path(file_path)

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return read_pdf(path)

    if suffix == ".docx":
        return read_docx(path)

    raise ValueError("Chỉ hỗ trợ PDF hoặc DOCX")


def read_pdf(path: Path):

    reader = PdfReader(str(path))

    text = ""

    for page in reader.pages:

        page_text = page.extract_text()

        if page_text:
            text += page_text + "\n"

    return text


def read_docx(path: Path):

    doc = Document(str(path))

    text = []

    for p in doc.paragraphs:

        if p.text.strip():
            text.append(p.text)

    return "\n".join(text)