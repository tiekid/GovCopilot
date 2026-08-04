import re
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class MeetingDocument:
    agency: str
    doc_type: str
    number: str
    title: str


class DocumentExtractor:

    def __init__(self):
        pass

    def extract(self, text: str) -> List[MeetingDocument]:

        documents = []

        current_agency = ""

        lines = text.splitlines()

        for line in lines:

            line = line.strip()

            if not line:
                continue

            # ----------------------------
            # Nhận diện cơ quan
            # ----------------------------

            m = re.match(r"^\d+\.\s*(.+?)\s+trình[:：]", line, re.IGNORECASE)

            if m:
                current_agency = m.group(1).strip()
                continue

            # ----------------------------
            # Tờ trình
            # ----------------------------

            docs = self._extract_doc(
                line,
                current_agency,
                "Tờ trình",
                r"Tờ trình\s+số\s+([0-9]+\/[A-Za-z\-]+)"
            )

            documents.extend(docs)

            # ----------------------------
            # Báo cáo
            # ----------------------------

            docs = self._extract_doc(
                line,
                current_agency,
                "Báo cáo",
                r"Báo cáo\s+số\s+([0-9]+\/[A-Za-z\-]+)"
            )

            documents.extend(docs)

            # ----------------------------
            # Công văn
            # ----------------------------

            docs = self._extract_doc(
                line,
                current_agency,
                "Công văn",
                r"Công văn\s+số\s+([0-9]+\/[A-Za-z\-]+)"
            )

            documents.extend(docs)

        return documents

    def _extract_doc(
        self,
        line,
        agency,
        doc_type,
        pattern
    ):

        result = []

        matches = re.finditer(pattern, line, re.IGNORECASE)

        for m in matches:

            number = m.group(1)

            title = line[m.end():].strip()

            title = title.lstrip(":")
            title = title.strip()

            result.append(
                MeetingDocument(
                    agency=agency,
                    doc_type=doc_type,
                    number=number,
                    title=title
                )
            )

        return result