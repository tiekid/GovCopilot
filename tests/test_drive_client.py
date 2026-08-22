"""Unit tests for agents/drive_client.py.

`requests` is fully mocked (patched at the point of use in
agents.drive_client) — no network access, no real API key required, no
real API calls made.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, List, Optional
from unittest.mock import patch

import requests

from agents.drive_client import (
    DriveApiError,
    DriveFileEntry,
    DriveForbiddenError,
    DriveNetworkError,
    download_binary,
    export_native_file,
    is_folder,
    is_native_google_file,
    list_folder,
    resolve_export_target,
)


class _FakeResponse:
    """Fake requests.Response supporting only what drive_client actually uses."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[dict] = None,
        text: str = "",
        chunks: Optional[List[bytes]] = None,
        iter_content_fn: Optional[Callable] = None,
    ) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text
        self._json_data = json_data or {}
        self._chunks = chunks or []
        self._iter_content_fn = iter_content_fn

    def json(self) -> dict:
        return self._json_data

    def iter_content(self, chunk_size: int):
        if self._iter_content_fn is not None:
            return self._iter_content_fn(chunk_size)
        return iter(self._chunks)


class ListFolderTests(unittest.TestCase):

    def test_parses_files_and_folders_including_missing_size(self) -> None:
        response = _FakeResponse(
            json_data={
                "files": [
                    {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf", "size": "429095"},
                    {"id": "f2", "name": "ND 13.4 - 9414", "mimeType": "application/vnd.google-apps.folder"},
                ]
            }
        )

        with patch("agents.drive_client.requests.get", return_value=response) as mock_get:
            entries = list_folder("test-key", "folder-id")

        self.assertEqual(
            entries,
            [
                DriveFileEntry(id="f1", name="a.pdf", mime_type="application/pdf", size=429095),
                DriveFileEntry(
                    id="f2", name="ND 13.4 - 9414", mime_type="application/vnd.google-apps.folder", size=None
                ),
            ],
        )
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["q"], "'folder-id' in parents")

    def test_403_raises_forbidden_error(self) -> None:
        response = _FakeResponse(status_code=403, text="The user does not have sufficient permissions")

        with patch("agents.drive_client.requests.get", return_value=response):
            with self.assertRaises(DriveForbiddenError):
                list_folder("test-key", "folder-id")

    def test_other_http_error_raises_generic_api_error(self) -> None:
        response = _FakeResponse(status_code=404, text="File not found")

        with patch("agents.drive_client.requests.get", return_value=response):
            with self.assertRaises(DriveApiError):
                list_folder("test-key", "folder-id")

    def test_connection_failure_raises_network_error(self) -> None:
        with patch(
            "agents.drive_client.requests.get",
            side_effect=requests.exceptions.ConnectionError("DNS lookup failed"),
        ):
            with self.assertRaises(DriveNetworkError):
                list_folder("test-key", "folder-id")


class DownloadBinaryTests(unittest.TestCase):

    def test_writes_streamed_content_to_dest_path(self) -> None:
        response = _FakeResponse(chunks=[b"hello ", b"world"])

        with TemporaryDirectory() as tmp_dir:
            dest_path = Path(tmp_dir) / "out.pdf"

            with patch("agents.drive_client.requests.get", return_value=response) as mock_get:
                download_binary("test-key", "file-id", dest_path)

            self.assertEqual(dest_path.read_bytes(), b"hello world")
            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["alt"], "media")
            self.assertTrue(kwargs["stream"])

    def test_403_raises_forbidden_error(self) -> None:
        response = _FakeResponse(status_code=403, text="Forbidden")

        with TemporaryDirectory() as tmp_dir:
            dest_path = Path(tmp_dir) / "out.pdf"

            with patch("agents.drive_client.requests.get", return_value=response):
                with self.assertRaises(DriveForbiddenError):
                    download_binary("test-key", "file-id", dest_path)

            self.assertFalse(dest_path.exists())

    def test_mid_stream_failure_raises_network_error_and_removes_partial_file(self) -> None:
        def raising_iter(chunk_size: int):
            yield b"partial-bytes"
            raise requests.exceptions.ConnectionError("connection dropped")

        response = _FakeResponse(iter_content_fn=raising_iter)

        with TemporaryDirectory() as tmp_dir:
            dest_path = Path(tmp_dir) / "out.pdf"

            with patch("agents.drive_client.requests.get", return_value=response):
                with self.assertRaises(DriveNetworkError):
                    download_binary("test-key", "file-id", dest_path)

            self.assertFalse(dest_path.exists())


class ExportNativeFileTests(unittest.TestCase):

    def test_calls_export_endpoint_with_mime_type_and_writes_content(self) -> None:
        response = _FakeResponse(chunks=[b"docx-bytes"])

        with TemporaryDirectory() as tmp_dir:
            dest_path = Path(tmp_dir) / "out.docx"

            with patch("agents.drive_client.requests.get", return_value=response) as mock_get:
                export_native_file(
                    "test-key",
                    "file-id",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    dest_path,
                )

            self.assertEqual(dest_path.read_bytes(), b"docx-bytes")
            args, kwargs = mock_get.call_args
            self.assertTrue(args[0].endswith("/file-id/export"))
            self.assertEqual(
                kwargs["params"]["mimeType"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )


class MimeTypeHelperTests(unittest.TestCase):

    def test_is_folder(self) -> None:
        self.assertTrue(is_folder("application/vnd.google-apps.folder"))
        self.assertFalse(is_folder("application/pdf"))

    def test_is_native_google_file_excludes_folder(self) -> None:
        self.assertTrue(is_native_google_file("application/vnd.google-apps.document"))
        self.assertFalse(is_native_google_file("application/vnd.google-apps.folder"))
        self.assertFalse(is_native_google_file("application/pdf"))

    def test_resolve_export_target_known_types(self) -> None:
        self.assertEqual(
            resolve_export_target("application/vnd.google-apps.document"),
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        )
        self.assertEqual(
            resolve_export_target("application/vnd.google-apps.spreadsheet"),
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        )
        self.assertEqual(resolve_export_target("application/vnd.google-apps.presentation"), ("application/pdf", ".pdf"))

    def test_resolve_export_target_unknown_type_raises(self) -> None:
        with self.assertRaises(DriveApiError):
            resolve_export_target("application/vnd.google-apps.form")


if __name__ == "__main__":
    unittest.main()
