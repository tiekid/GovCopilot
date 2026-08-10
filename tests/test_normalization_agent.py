"""Unit tests for agents/normalization.py's ND-grouping/bundling logic.

Uses real temp files on disk (small, arbitrary content — never opened
for content by NormalizationAgent itself, only by zipfile/os.stat) so
_build_zip/_fallback_smallest_file exercise real filesystem behavior,
matching this project's evidence-first testing style.
"""

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.normalization import NormalizationAgent, _UNASSIGNED_MA_ND
from models.document import MeetingDocument
from models.meeting import AgendaItem, Meeting


def _write_file(directory: Path, name: str, size_bytes: int) -> str:
    path = directory / name
    path.write_bytes(b"x" * size_bytes)
    return str(path)


class NormalizationAgentTests(unittest.TestCase):

    def test_groups_documents_by_agenda_item_and_writes_zip_and_meta(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            doc1 = MeetingDocument(
                number="9047/TTr-SXD",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_9047_TTr-SXD.pdf", 100),
                agenda_item_index=1,
            )
            doc2 = MeetingDocument(
                number="8069/BC-SYT",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_8069_BC-SYT.docx", 200),
                agenda_item_index=1,
            )

            meeting = Meeting(
                meeting_name="Họp giao ban",
                meeting_date="03/08/2026",
                agenda=[AgendaItem(index=1, agency="Sở Xây dựng", title="Quy hoạch")],
                documents=[doc1, doc2],
            )

            agent = NormalizationAgent(Path(output_dir))
            groups = agent.normalize(meeting)

            self.assertEqual(len(groups), 1)
            group = groups[0]
            self.assertEqual(group.ma_nd, "ND01")
            self.assertTrue(Path(group.zip_path).exists())
            self.assertTrue(Path(group.meta_path).exists())

            with zipfile.ZipFile(group.zip_path) as archive:
                names = set(archive.namelist())
            self.assertEqual(names, {"Đính kèm_9047_TTr-SXD.pdf", "Đính kèm_8069_BC-SYT.docx"})

    def test_identifies_to_trinh_file_by_filename(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            to_trinh = MeetingDocument(
                number="9047/TTr-SXD",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_9047_TTr-SXD.pdf", 500),
                agenda_item_index=1,
            )
            other = MeetingDocument(
                number="8069/BC-SYT",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_8069_BC-SYT.docx", 10),
                agenda_item_index=1,
            )

            meeting = Meeting(
                meeting_date="03/08/2026",
                agenda=[AgendaItem(index=1, agency="Sở Xây dựng", title="Quy hoạch")],
                documents=[to_trinh, other],
            )

            agent = NormalizationAgent(Path(output_dir))
            group = agent.normalize(meeting)[0]

            # Matched by "TTr" in the filename, not by being the smallest
            # file — the smaller .docx would win a size-based fallback.
            self.assertEqual(group.to_trinh_file, "Đính kèm_9047_TTr-SXD.pdf")

            meta = json.loads(Path(group.meta_path).read_text(encoding="utf-8"))
            self.assertEqual(meta["to_trinh_file"], "Đính kèm_9047_TTr-SXD.pdf")

    def test_falls_back_to_smallest_pdf_docx_by_size_when_no_name_matches(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            large = MeetingDocument(
                number="8069/BC-SYT",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_8069_BC-SYT.pdf", 1000),
                agenda_item_index=1,
            )
            small = MeetingDocument(
                number="8143/CV-SNV",
                downloaded=True,
                local_path=_write_file(downloads, "Đính kèm_8143_CV-SNV.docx", 10),
                agenda_item_index=1,
            )

            meeting = Meeting(
                meeting_date="03/08/2026",
                agenda=[AgendaItem(index=1, agency="Sở Y tế", title="Báo cáo")],
                documents=[large, small],
            )

            agent = NormalizationAgent(Path(output_dir))

            with self.assertLogs("agents.normalization", level="WARNING") as logs:
                group = agent.normalize(meeting)[0]

            self.assertEqual(group.to_trinh_file, "Đính kèm_8143_CV-SNV.docx")
            self.assertTrue(any("falling back" in message.lower() for message in logs.output))

    def test_unassigned_documents_grouped_separately_and_logged(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            document = MeetingDocument(
                number="9999/TTr-GHOST",
                downloaded=True,
                local_path=_write_file(downloads, "ghost.pdf", 10),
                agenda_item_index=None,
            )

            meeting = Meeting(meeting_date="03/08/2026", agenda=[], documents=[document])

            agent = NormalizationAgent(Path(output_dir))
            groups = agent.normalize(meeting)

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].ma_nd, _UNASSIGNED_MA_ND)

    def test_trang_thai_day_du_false_when_a_document_was_not_downloaded(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            downloaded_doc = MeetingDocument(
                number="9047/TTr-SXD",
                downloaded=True,
                local_path=_write_file(downloads, "9047.pdf", 10),
                agenda_item_index=1,
            )
            missing_doc = MeetingDocument(
                number="8069/BC-SYT",
                downloaded=False,
                local_path="",
                agenda_item_index=1,
            )

            meeting = Meeting(
                meeting_date="03/08/2026",
                agenda=[AgendaItem(index=1, agency="Sở Xây dựng", title="Quy hoạch")],
                documents=[downloaded_doc, missing_doc],
            )

            agent = NormalizationAgent(Path(output_dir))

            with self.assertLogs("agents.normalization", level="WARNING") as logs:
                group = agent.normalize(meeting)[0]

            self.assertFalse(group.trang_thai_day_du)
            # The undownloaded document is still counted (visible in the
            # group), but excluded from the zip's actual file list.
            with zipfile.ZipFile(group.zip_path) as archive:
                self.assertEqual(archive.namelist(), ["9047.pdf"])
            self.assertTrue(any("8069/BC-SYT" in message for message in logs.output))

    def test_meta_json_schema_fields(self) -> None:
        with TemporaryDirectory() as downloads_dir, TemporaryDirectory() as output_dir:
            downloads = Path(downloads_dir)

            document = MeetingDocument(
                number="9047/TTr-SXD",
                downloaded=True,
                local_path=_write_file(downloads, "9047_TTr-SXD.pdf", 10),
                agenda_item_index=1,
            )

            meeting = Meeting(
                meeting_date="03/08/2026",
                agenda=[AgendaItem(index=1, agency="Sở Xây dựng", title="Quy hoạch")],
                documents=[document],
            )

            agent = NormalizationAgent(Path(output_dir))
            group = agent.normalize(meeting)[0]

            meta = json.loads(Path(group.meta_path).read_text(encoding="utf-8"))

            self.assertEqual(meta["ma_nd"], "ND01")
            self.assertEqual(meta["ky_hop"], "03/08/2026")
            self.assertEqual(meta["nguon"], "vbdh")
            self.assertEqual(meta["linh_vuc"], "")
            self.assertEqual(meta["co_quan_trinh"], "Sở Xây dựng")
            self.assertEqual(meta["danh_sach_file"], ["9047_TTr-SXD.pdf"])
            self.assertEqual(meta["to_trinh_file"], "9047_TTr-SXD.pdf")
            self.assertTrue(meta["trang_thai_day_du"])
            self.assertTrue(meta["thoi_gian_thu_thap"].startswith("20"))
            self.assertIn("+07:00", meta["thoi_gian_thu_thap"])


if __name__ == "__main__":
    unittest.main()
