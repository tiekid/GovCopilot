"""Unit tests for DownloadAgent.download_from_drive() (agents/download.py).

agents/drive_client.py is fully mocked at the point of use — no network
access, no real API key required. This is the domain-logic side of the
split (folder traversal, document matching, native-vs-binary dispatch);
agents/drive_client.py's own transport behavior is covered separately
in tests/test_drive_client.py.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.download import DownloadAgent, _DRIVE_MISSING_API_KEY_MESSAGE
from agents.drive_client import DriveApiError, DriveFileEntry, DriveForbiddenError, DriveNetworkError
from models.document import MeetingDocument


def _agent(tmp_dir: str, drive_api_key: str = "test-key") -> DownloadAgent:
    # browser_session is never touched by download_from_drive — only
    # download() (the VBĐH path) uses it.
    return DownloadAgent(None, Path(tmp_dir), drive_api_key=drive_api_key)  # type: ignore[arg-type]


class MissingApiKeyTests(unittest.TestCase):

    def test_missing_api_key_fails_without_calling_drive_client(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir, drive_api_key="")

            with patch("agents.drive_client.list_folder") as mock_list:
                result = agent.download_from_drive(MeetingDocument(number="9414/TTr-SXD"), "folder-id")

        self.assertFalse(result.success)
        self.assertEqual(result.error, _DRIVE_MISSING_API_KEY_MESSAGE)
        mock_list.assert_not_called()


class FolderTraversalAndMatchingTests(unittest.TestCase):
    """Real evidence: an ND folder ("ND 13.4 - 9414") with 2 files
    directly inside, and a parent meeting folder whose direct children
    are all ND subfolders (2026-08-22 Cowork session)."""

    def test_direct_files_folder_matches_and_downloads_binary(self) -> None:
        """The exact shape confirmed by scripts/test_drive_api_v3.py."""

        document = MeetingDocument(number="9414/TTr-SXD")
        files = [
            DriveFileEntry(
                id="f1",
                name="TMTT-QHC HOA THANH.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=6676644,
            ),
            DriveFileEntry(
                id="f2",
                name="9414_TTr-SXD_31-07-2026_26-TTr QUY HOACH CHUNG HOA THANH-ks.signed.pdf",
                mime_type="application/pdf",
                size=429095,
            ),
        ]

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", return_value=files) as mock_list, \
                 patch("agents.drive_client.download_binary") as mock_download:
                result = agent.download_from_drive(document, "nd-folder-id")

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertTrue(document.downloaded)
        self.assertTrue(
            document.local_path.endswith(
                "9414_TTr-SXD_31-07-2026_26-TTr QUY HOACH CHUNG HOA THANH-ks.signed.pdf"
            )
        )
        mock_list.assert_called_once_with("test-key", "nd-folder-id")
        mock_download.assert_called_once()
        args, _ = mock_download.call_args
        self.assertEqual(args[0], "test-key")
        self.assertEqual(args[1], "f2")

    def test_parent_folder_recurses_one_level_into_subfolders(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")

        subfolder = DriveFileEntry(id="sub-1", name="ND 13.4 - 9414", mime_type="application/vnd.google-apps.folder")
        other_subfolder = DriveFileEntry(id="sub-2", name="ND 1 - 338", mime_type="application/vnd.google-apps.folder")
        matching_file = DriveFileEntry(id="f2", name="9414_TTr-SXD_report.pdf", mime_type="application/pdf", size=1000)
        unrelated_file = DriveFileEntry(id="f3", name="338_QD.pdf", mime_type="application/pdf", size=500)

        def fake_list_folder(api_key: str, folder_id: str):
            return {
                "parent-id": [subfolder, other_subfolder],
                "sub-1": [matching_file],
                "sub-2": [unrelated_file],
            }[folder_id]

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", side_effect=fake_list_folder), \
                 patch("agents.drive_client.download_binary") as mock_download:
                result = agent.download_from_drive(document, "parent-id")

        self.assertTrue(result.success)
        mock_download.assert_called_once()
        args, _ = mock_download.call_args
        self.assertEqual(args[1], "f2")

    def test_folder_nested_two_levels_deep_is_skipped_not_traversed(self) -> None:
        """Only one level of subfolder recursion is ever performed — a
        folder found inside a subfolder is unexpected structure, logged
        and skipped, never itself listed."""

        document = MeetingDocument(number="9414/TTr-SXD")

        subfolder = DriveFileEntry(id="sub-1", name="ND 13.4 - 9414", mime_type="application/vnd.google-apps.folder")
        nested_folder = DriveFileEntry(
            id="nested-1", name="unexpected nested folder", mime_type="application/vnd.google-apps.folder"
        )

        def fake_list_folder(api_key: str, folder_id: str):
            if folder_id == "parent-id":
                return [subfolder]
            if folder_id == "sub-1":
                return [nested_folder]
            raise AssertionError(f"must never recurse into nested folder '{folder_id}'")

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", side_effect=fake_list_folder):
                result = agent.download_from_drive(document, "parent-id")

        self.assertFalse(result.success)
        self.assertIn("No file matching", result.error)

    def test_no_matching_file_is_a_reportable_failure_not_a_crash(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")
        files = [DriveFileEntry(id="f1", name="unrelated.pdf", mime_type="application/pdf", size=1)]

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", return_value=files):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertFalse(document.downloaded)
        self.assertIn("No file matching document number '9414/TTr-SXD'", result.error)

    def test_multiple_matching_files_is_a_reportable_failure(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")
        files = [
            DriveFileEntry(id="f1", name="9414_TTr-SXD_v1.pdf", mime_type="application/pdf", size=1),
            DriveFileEntry(id="f2", name="9414_TTr-SXD_v2.pdf", mime_type="application/pdf", size=1),
        ]

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", return_value=files):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertIn("Multiple files matched document number '9414/TTr-SXD'", result.error)

    def test_document_number_not_starting_with_digits_never_matches(self) -> None:
        """The matching heuristic anchors to the start of the string —
        a number embedded elsewhere in document.number is deliberately
        not treated as a match candidate (see agents/download.py's
        _DRIVE_NUMBER_PREFIX_PATTERN)."""

        document = MeetingDocument(number="TTr-SXD-9414")
        files = [DriveFileEntry(id="f1", name="9414_file.pdf", mime_type="application/pdf", size=1)]

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", return_value=files):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertIn("No file matching", result.error)


class NativeGoogleFileDispatchTests(unittest.TestCase):

    def test_native_google_document_dispatches_to_export_with_docx_extension(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")
        native_file = DriveFileEntry(
            id="f1", name="9414 To trinh", mime_type="application/vnd.google-apps.document", size=None
        )

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", return_value=[native_file]), \
                 patch("agents.drive_client.export_native_file") as mock_export:
                result = agent.download_from_drive(document, "folder-id")

        self.assertTrue(result.success)
        mock_export.assert_called_once()
        args, _ = mock_export.call_args
        self.assertEqual(args[0], "test-key")
        self.assertEqual(args[1], "f1")
        self.assertEqual(args[2], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(str(args[3]).endswith(".docx"))
        self.assertTrue(document.local_path.endswith(".docx"))


class TypedErrorReportingTests(unittest.TestCase):
    """403 / network / other API errors must stay distinguishable in
    DownloadResult.error, never collapsed into one generic message."""

    def test_forbidden_error_is_prefixed_distinctly(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", side_effect=DriveForbiddenError("no permission")):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertTrue(result.error.startswith("[Drive permission denied]"))

    def test_network_error_is_prefixed_distinctly(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", side_effect=DriveNetworkError("dns failed")):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertTrue(result.error.startswith("[Drive network error]"))

    def test_generic_api_error_is_prefixed_distinctly(self) -> None:
        document = MeetingDocument(number="9414/TTr-SXD")

        with TemporaryDirectory() as tmp_dir:
            agent = _agent(tmp_dir)

            with patch("agents.drive_client.list_folder", side_effect=DriveApiError("500 server error")):
                result = agent.download_from_drive(document, "folder-id")

        self.assertFalse(result.success)
        self.assertTrue(result.error.startswith("[Drive API error]"))


if __name__ == "__main__":
    unittest.main()
