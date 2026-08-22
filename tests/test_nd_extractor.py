"""Unit tests for ai/nd_extractor.py.

100% mocked — no real Gemini/AI API call. Uses tests/fakes.py::FakeProvider
(the same fake test_ai_invitation_extractor.py already uses) for
provider injection, and patches ai.nd_extractor.read_invitation at the
point of use so bundle zips only need correctly-named entries with
arbitrary bytes — the read step itself is mocked, mirroring how
tests/test_download_agent_drive.py mocks agents.drive_client instead of
hitting a real API.
"""

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.normalization import NormalizedAgendaGroup
from ai.nd_extractor import NDContentExtractor, NDExtractionResult
from providers.ai_provider import ProviderConfigurationError
from tests.fakes import FakeProvider


def _write_bundle(tmp_dir: str, ma_nd: str, file_contents: dict, meta: dict) -> NormalizedAgendaGroup:
    """Writes a real {ma_nd}.zip + {ma_nd}.meta.json, returns the matching group.

    `file_contents` maps filename -> arbitrary bytes (real parsing is
    always mocked via read_invitation, so the bytes never need to be a
    real parseable PDF/DOCX).
    """

    zip_path = Path(tmp_dir) / f"{ma_nd}.zip"
    meta_path = Path(tmp_dir) / f"{ma_nd}.meta.json"

    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in file_contents.items():
            archive.writestr(name, content)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    return NormalizedAgendaGroup(
        ma_nd=ma_nd,
        agenda_item_index=1,
        zip_path=str(zip_path),
        meta_path=str(meta_path),
    )


class SuccessfulExtractionTests(unittest.TestCase):

    def test_extracts_successfully_for_nd_with_multiple_readable_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            group = _write_bundle(
                tmp_dir,
                "ND01",
                {"a.pdf": b"fake pdf bytes", "b.docx": b"fake docx bytes"},
                {"co_quan_trinh": "Sở Xây dựng", "ky_hop": "Kỳ họp thứ 6"},
            )

            provider = FakeProvider(response="## 1. Số hiệu...\nNội dung trích xuất.")
            extractor = NDContentExtractor(provider=provider)

            texts_by_name = {"a.pdf": "Nội dung file A.", "b.docx": "Nội dung file B."}

            with patch(
                "ai.nd_extractor.read_invitation", side_effect=lambda path: texts_by_name[Path(path).name]
            ):
                results = extractor.extract([group])

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertTrue(result.extracted)
            self.assertIsNone(result.skip_reason)
            self.assertEqual(result.ma_nd, "ND01")
            self.assertEqual(result.agenda_item_index, 1)

            self.assertEqual(provider.call_count, 1)
            self.assertEqual(provider.last_system_prompt, extractor._prompt)
            self.assertIn("Nội dung file A.", provider.last_user_prompt)
            self.assertIn("Nội dung file B.", provider.last_user_prompt)
            self.assertIn("Sở Xây dựng", provider.last_user_prompt)
            self.assertIn("Kỳ họp thứ 6", provider.last_user_prompt)
            self.assertIn("ND01", provider.last_user_prompt)

            extract_path = Path(result.extract_path)
            self.assertTrue(extract_path.exists())
            self.assertEqual(extract_path.name, "ND01.extract.md")
            self.assertIn("Nội dung trích xuất.", extract_path.read_text(encoding="utf-8"))


class ScanDetectionAndSkipTests(unittest.TestCase):

    def test_skips_nd_when_a_file_has_zero_extractable_characters(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            group = _write_bundle(
                tmp_dir, "ND02", {"a.pdf": b"...", "scanned.pdf": b"..."}, {}
            )

            provider = FakeProvider(response="should never be used")
            extractor = NDContentExtractor(provider=provider)

            texts_by_name = {"a.pdf": "Có nội dung.", "scanned.pdf": ""}

            with patch(
                "ai.nd_extractor.read_invitation", side_effect=lambda path: texts_by_name[Path(path).name]
            ):
                results = extractor.extract([group])

        result = results[0]
        self.assertFalse(result.extracted)
        self.assertIsNone(result.extract_path)
        self.assertIn("scanned.pdf", result.skip_reason)
        self.assertIn("no extractable text", result.skip_reason)
        self.assertEqual(provider.call_count, 0)
        self.assertFalse((Path(tmp_dir) / "ND02.extract.md").exists())

    def test_skips_nd_with_no_files_in_bundle(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "ND03.zip"
            with zipfile.ZipFile(zip_path, "w"):
                pass  # empty archive
            meta_path = Path(tmp_dir) / "ND03.meta.json"
            meta_path.write_text("{}", encoding="utf-8")

            group = NormalizedAgendaGroup(
                ma_nd="ND03", agenda_item_index=3, zip_path=str(zip_path), meta_path=str(meta_path)
            )

            provider = FakeProvider(response="should never be used")
            extractor = NDContentExtractor(provider=provider)

            results = extractor.extract([group])

        result = results[0]
        self.assertFalse(result.extracted)
        self.assertIn("no files", result.skip_reason)
        self.assertEqual(provider.call_count, 0)

    def test_skips_nd_when_bundle_zip_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            group = NormalizedAgendaGroup(
                ma_nd="ND04",
                agenda_item_index=4,
                zip_path=str(Path(tmp_dir) / "ND04.zip"),
                meta_path=str(Path(tmp_dir) / "ND04.meta.json"),
            )

            provider = FakeProvider(response="should never be used")
            extractor = NDContentExtractor(provider=provider)

            results = extractor.extract([group])

        result = results[0]
        self.assertFalse(result.extracted)
        self.assertIn("Bundle not found", result.skip_reason)
        self.assertEqual(provider.call_count, 0)

    def test_unsupported_file_type_skips_nd(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            group = _write_bundle(tmp_dir, "ND05", {"data.xlsx": b"..."}, {})

            provider = FakeProvider(response="should never be used")
            extractor = NDContentExtractor(provider=provider)

            with patch(
                "ai.nd_extractor.read_invitation",
                side_effect=ValueError("Chỉ hỗ trợ PDF hoặc DOCX"),
            ):
                results = extractor.extract([group])

        result = results[0]
        self.assertFalse(result.extracted)
        self.assertIn("Unsupported file type", result.skip_reason)
        self.assertIn("data.xlsx", result.skip_reason)
        self.assertEqual(provider.call_count, 0)


class ProviderErrorTests(unittest.TestCase):

    def test_provider_error_does_not_crash_extract_batch(self) -> None:
        """A provider failure on one ND must not abort the batch — the
        other ND in the same extract() call still succeeds."""

        with TemporaryDirectory() as tmp_dir:
            failing_group = _write_bundle(tmp_dir, "ND06", {"a.pdf": b"..."}, {})
            ok_group = _write_bundle(tmp_dir, "ND07", {"b.pdf": b"..."}, {})

            provider = FakeProvider(response="Trích xuất thành công.")

            original_generate = provider.generate
            call_log = []

            def flaky_generate(system_prompt: str, user_prompt: str) -> str:
                call_log.append(user_prompt)
                if len(call_log) == 1:
                    raise TimeoutError("Gemini request timed out")
                return original_generate(system_prompt, user_prompt)

            provider.generate = flaky_generate  # type: ignore[method-assign]

            extractor = NDContentExtractor(provider=provider)

            with patch("ai.nd_extractor.read_invitation", return_value="Nội dung hợp lệ."):
                results = extractor.extract([failing_group, ok_group])

            self.assertEqual(len(results), 2)

            failed_result, ok_result = results
            self.assertFalse(failed_result.extracted)
            self.assertIn("AI provider error", failed_result.skip_reason)
            self.assertIn("timed out", failed_result.skip_reason)

            self.assertTrue(ok_result.extracted)
            self.assertIsNotNone(ok_result.extract_path)
            self.assertTrue(Path(ok_result.extract_path).exists())


class ConstructionTests(unittest.TestCase):

    def test_missing_api_key_raises_at_construction(self) -> None:
        with patch(
            "ai.nd_extractor.create_provider", side_effect=ProviderConfigurationError("no key")
        ):
            with self.assertRaises(ProviderConfigurationError):
                NDContentExtractor()


if __name__ == "__main__":
    unittest.main()
