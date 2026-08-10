"""Agent that groups downloaded documents by agenda item (ND) and
bundles each group for the upcoming AI review stage.

Runs after DownloadAgent: for each ND (AgendaItem) in a Meeting, zips
every downloaded MeetingDocument referenced under it into NDxx.zip and
writes a NDxx.meta.json describing the bundle. Never reads PDF/DOCX
content directly — Tờ trình identification and the "smallest file"
fallback both operate on filenames/file size only, never file content
(that stays InvitationReader's exclusive job — see ARCHITECTURE.md's
hard rules).

Documents whose agenda_item_index couldn't be determined (see
agents/meeting_parser.py) are never silently dropped — they're
collected into a distinct "unassigned ND" group instead, logged as a
WARNING.
"""

import json
import logging
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from models.document import MeetingDocument
from models.meeting import Meeting

logger = logging.getLogger(__name__)

# Only real source this pipeline produces today — VBĐH. "qr_drive" and
# "manual" are forward-looking values for sources no code path
# currently populates; not modeled as a MeetingDocument field until one
# actually exists (see docs/ARCHITECTURE.md's NormalizationAgent entry).
_SOURCE = "vbdh"

# Extended here, not scattered across the module, if more keywords are
# ever needed — matched case/diacritic-insensitively (see _fold())
# against the downloaded file's name, never its content.
_TO_TRINH_KEYWORDS: tuple = ("to trinh", "ttr")

# Fallback candidates are restricted to these extensions, matching the
# original requirement ("chọn file PDF/DOCX ít trang nhất") — now by
# file size rather than page count (no PDF/DOCX content is opened).
_FALLBACK_EXTENSIONS: tuple = (".pdf", ".docx")

# Sentinel ma_nd for documents whose ND couldn't be determined —
# deliberately not of the form "NDxx" so it can never collide with a
# real agenda item's code.
_UNASSIGNED_MA_ND = "ND_UNASSIGNED"

_VN_TIMEZONE = timezone(timedelta(hours=7))


@dataclass
class NormalizedAgendaGroup:
    """Result of bundling one ND's downloaded documents."""

    ma_nd: str
    agenda_item_index: Optional[int]
    documents: List[MeetingDocument] = field(default_factory=list)
    zip_path: str = ""
    meta_path: str = ""
    to_trinh_file: Optional[str] = None
    trang_thai_day_du: bool = False


class NormalizationAgent:
    """Groups downloaded MeetingDocuments by agenda item and bundles each
    group into NDxx.zip + NDxx.meta.json.

    Never reads PDF/DOCX content, never searches VBĐH, never performs
    AI analysis — purely reorganizes what DownloadAgent already
    produced (MeetingDocument.local_path) using metadata already on
    the Meeting object.
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def normalize(self, meeting: Meeting) -> List[NormalizedAgendaGroup]:

        groups = self._group_documents(meeting.documents)
        agenda_by_index = {item.index: item for item in meeting.agenda}

        results: List[NormalizedAgendaGroup] = []

        for agenda_item_index, documents in groups.items():

            agenda_item = agenda_by_index.get(agenda_item_index) if agenda_item_index is not None else None

            if agenda_item_index is not None and agenda_item is None:
                logger.warning(
                    "agenda_item_index %d has no matching AgendaItem; treating "
                    "%d document(s) as unassigned",
                    agenda_item_index,
                    len(documents),
                )

            if agenda_item is not None:
                ma_nd = self._format_ma_nd(agenda_item_index)
                agency = agenda_item.agency
            else:
                ma_nd = _UNASSIGNED_MA_ND
                agency = ""

            results.append(
                self._build_group(ma_nd, agenda_item_index, agency, meeting.meeting_date, documents)
            )

        logger.info(
            "Normalized %d agenda group(s) for meeting '%s'", len(results), meeting.meeting_name
        )

        return results

    @staticmethod
    def _group_documents(
        documents: List[MeetingDocument],
    ) -> Dict[Optional[int], List[MeetingDocument]]:

        groups: Dict[Optional[int], List[MeetingDocument]] = {}

        for document in documents:
            groups.setdefault(document.agenda_item_index, []).append(document)

        return groups

    def _build_group(
        self,
        ma_nd: str,
        agenda_item_index: Optional[int],
        agency: str,
        meeting_date: str,
        documents: List[MeetingDocument],
    ) -> NormalizedAgendaGroup:

        downloaded = [d for d in documents if d.downloaded and d.local_path]
        missing = [d for d in documents if not (d.downloaded and d.local_path)]

        for document in missing:
            logger.warning(
                "Document number %s in %s was not downloaded; excluded from the bundle",
                document.number,
                ma_nd,
            )

        zip_path = self._build_zip(ma_nd, downloaded)

        to_trinh_document = self._find_to_trinh_file(downloaded)

        if to_trinh_document is None and downloaded:
            to_trinh_document = self._fallback_smallest_file(downloaded)
            if to_trinh_document is not None:
                logger.warning(
                    "No filename in %s matched Tờ trình keywords %s; falling back "
                    "to smallest file by size: %s",
                    ma_nd,
                    _TO_TRINH_KEYWORDS,
                    Path(to_trinh_document.local_path).name,
                )

        trang_thai_day_du = len(missing) == 0 and len(documents) > 0

        meta = self._build_meta(
            ma_nd, meeting_date, agency, downloaded, to_trinh_document, trang_thai_day_du
        )
        meta_path = self._write_meta(ma_nd, meta)

        return NormalizedAgendaGroup(
            ma_nd=ma_nd,
            agenda_item_index=agenda_item_index,
            documents=documents,
            zip_path=str(zip_path),
            meta_path=str(meta_path),
            to_trinh_file=Path(to_trinh_document.local_path).name if to_trinh_document else None,
            trang_thai_day_du=trang_thai_day_du,
        )

    def _build_zip(self, ma_nd: str, documents: List[MeetingDocument]) -> Path:

        self._output_dir.mkdir(parents=True, exist_ok=True)

        zip_path = self._output_dir / f"{ma_nd}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for document in documents:
                path = Path(document.local_path)

                if not path.exists():
                    logger.warning(
                        "File for document number %s not found on disk: %s", document.number, path
                    )
                    continue

                archive.write(path, arcname=path.name)

        logger.info("Wrote %s with %d file(s)", zip_path, len(documents))

        return zip_path

    @staticmethod
    def _find_to_trinh_file(documents: List[MeetingDocument]) -> Optional[MeetingDocument]:
        """Identify the Tờ trình file by filename only — never by content."""

        for document in documents:
            filename = Path(document.local_path).name
            folded = _fold(filename)

            if any(keyword in folded for keyword in _TO_TRINH_KEYWORDS):
                logger.info(
                    "Identified Tờ trình file for document number %s: %s",
                    document.number,
                    filename,
                )
                return document

        return None

    @staticmethod
    def _fallback_smallest_file(documents: List[MeetingDocument]) -> Optional[MeetingDocument]:
        """Smallest PDF/DOCX by file size — never opens or reads the file."""

        candidates = [d for d in documents if Path(d.local_path).suffix.lower() in _FALLBACK_EXTENSIONS]

        if not candidates:
            return None

        return min(candidates, key=lambda d: Path(d.local_path).stat().st_size)

    @staticmethod
    def _build_meta(
        ma_nd: str,
        meeting_date: str,
        agency: str,
        documents: List[MeetingDocument],
        to_trinh_document: Optional[MeetingDocument],
        trang_thai_day_du: bool,
    ) -> dict:

        return {
            "ma_nd": ma_nd,
            "ky_hop": meeting_date,
            "nguon": _SOURCE,
            "linh_vuc": "",
            "co_quan_trinh": agency,
            "danh_sach_file": [Path(d.local_path).name for d in documents],
            "to_trinh_file": Path(to_trinh_document.local_path).name if to_trinh_document else None,
            "trang_thai_day_du": trang_thai_day_du,
            "thoi_gian_thu_thap": datetime.now(_VN_TIMEZONE).isoformat(),
        }

    def _write_meta(self, ma_nd: str, meta: dict) -> Path:

        self._output_dir.mkdir(parents=True, exist_ok=True)

        meta_path = self._output_dir / f"{ma_nd}.meta.json"

        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("Wrote %s", meta_path)

        return meta_path

    @staticmethod
    def _format_ma_nd(agenda_item_index: int) -> str:
        return f"ND{agenda_item_index:02d}"


def _fold(text: str) -> str:
    """Lowercase, diacritic-stripped form for case/diacritic-insensitive matching."""

    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")

    return without_marks.lower()
