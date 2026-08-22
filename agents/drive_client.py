"""Transport-only Google Drive API v3 client (API key, no OAuth).

Backs `DownloadAgent.download_from_drive()` (agents/download.py). Mirrors
the split already established for AI providers (see providers/): this
module returns raw listings and bytes only — folder traversal, document
matching, and native-vs-binary dispatch decisions all live in
`DownloadAgent`, never here.

Confirmed against a real, "Anyone with the link" shared folder
(scripts/test_drive_api_v3.py, 2026-08-22): `files.list` scoped to a
folder via `'<id>' in parents`, `files.get?alt=media` for original
bytes, byte-exact size match against the API-reported size. The
`files.export` path (for native Google Docs/Sheets/Slides, which have
no binary content to fetch via `alt=media`) is implemented per the
Drive API v3 reference but has not yet been exercised against a real
native file — no Google-native file has been observed in any real ND
folder so far (see docs/GovCopilot-v2-kien-truc.md).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3/files"
_LIST_FIELDS = "files(id,name,mimeType,size)"
_REQUEST_TIMEOUT_SECONDS = 30
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# Verified against the real API response (scripts/test_drive_api_v3.py
# and the 2026-08-22 parent-folder confirmation call): every ND
# subfolder entry carries exactly this mimeType.
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Every native Google file type (Docs, Sheets, Slides, Forms, ...)
# shares this prefix and has no downloadable binary content — must go
# through files.export instead of files.get?alt=media.
_GOOGLE_NATIVE_MIME_PREFIX = "application/vnd.google-apps."

# export mimeType + file extension for each native Google type this
# pipeline is expected to encounter. Not yet exercised against a real
# file — see module docstring.
_NATIVE_EXPORT_TARGETS: Dict[str, Tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}


class DriveApiError(Exception):
    """Raised for any Drive API failure that isn't a connection-level or 403 error.

    Always the type callers see for a Drive HTTP error the more
    specific subclasses below don't cover (404, 500, an unsupported
    native mimeType, ...) — a raw `requests`/SDK exception never
    escapes this module.
    """


class DriveForbiddenError(DriveApiError):
    """Raised on HTTP 403 — a permission/sharing problem, not a transient failure.

    Distinguished from DriveNetworkError/DriveApiError specifically so
    a folder shared more restrictively than "Anyone with the link"
    (the only sharing mode confirmed working so far) is diagnosed
    immediately as a sharing issue, never mistaken for a flaky
    connection.
    """


class DriveNetworkError(DriveApiError):
    """Raised when no HTTP response was received at all (connection/timeout/DNS)."""


@dataclass
class DriveFileEntry:
    """One entry returned by files.list — a file or a folder."""

    id: str
    name: str
    mime_type: str

    # None for native Google files (Docs/Sheets/Slides report no size)
    # and always absent for folders.
    size: Optional[int] = None


def list_folder(api_key: str, folder_id: str) -> List[DriveFileEntry]:
    """Return every direct child (file or folder) of `folder_id`.

    One level only — does not recurse. Folder traversal is
    DownloadAgent's responsibility (see agents/download.py), not this
    module's.
    """

    logger.info("Listing Drive folder %s", folder_id)

    response = _get(
        _DRIVE_API_BASE_URL,
        {"q": f"'{folder_id}' in parents", "fields": _LIST_FIELDS, "key": api_key},
    )
    _raise_for_status(response, f"files.list failed for folder '{folder_id}'")

    entries = [
        DriveFileEntry(
            id=entry["id"],
            name=entry["name"],
            mime_type=entry["mimeType"],
            size=int(entry["size"]) if "size" in entry else None,
        )
        for entry in response.json().get("files", [])
    ]

    logger.info("Drive folder %s contains %d entries", folder_id, len(entries))

    return entries


def download_binary(api_key: str, file_id: str, dest_path: Path) -> None:
    """Download a file's original bytes via files.get?alt=media."""

    logger.info("Downloading Drive file %s -> %s", file_id, dest_path)

    response = _get(
        f"{_DRIVE_API_BASE_URL}/{file_id}",
        {"alt": "media", "key": api_key},
        stream=True,
    )
    _raise_for_status(response, f"files.get?alt=media failed for file '{file_id}'")
    _stream_to_file(response, dest_path)


def export_native_file(api_key: str, file_id: str, export_mime_type: str, dest_path: Path) -> None:
    """Export a native Google Docs/Sheets/Slides file via files.export.

    Native Google files have no binary content to fetch via
    files.get?alt=media — this is the only way to retrieve them.
    """

    logger.info("Exporting Drive file %s as '%s' -> %s", file_id, export_mime_type, dest_path)

    response = _get(
        f"{_DRIVE_API_BASE_URL}/{file_id}/export",
        {"mimeType": export_mime_type, "key": api_key},
        stream=True,
    )
    _raise_for_status(response, f"files.export failed for file '{file_id}'")
    _stream_to_file(response, dest_path)


def is_folder(mime_type: str) -> bool:
    return mime_type == _FOLDER_MIME_TYPE


def is_native_google_file(mime_type: str) -> bool:
    """Does `mime_type` identify a native Google file (Docs/Sheets/Slides/...)?

    Excludes folders, which share the same vendor prefix but aren't
    downloadable content at all.
    """

    return mime_type.startswith(_GOOGLE_NATIVE_MIME_PREFIX) and not is_folder(mime_type)


def resolve_export_target(mime_type: str) -> Tuple[str, str]:
    """Return (export_mime_type, file_extension) for a native Google mimeType.

    Raises DriveApiError if `mime_type` has no configured export
    target — this pipeline only knows how to export Docs, Sheets, and
    Slides today (see _NATIVE_EXPORT_TARGETS).
    """

    try:
        return _NATIVE_EXPORT_TARGETS[mime_type]
    except KeyError:
        raise DriveApiError(
            f"No export mapping configured for native Google mimeType '{mime_type}'"
        ) from None


def _get(url: str, params: Dict[str, str], stream: bool = False) -> requests.Response:
    """Issue a GET request, converting any connection-level failure to DriveNetworkError."""

    try:
        return requests.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS, stream=stream)
    except requests.exceptions.RequestException as exc:
        raise DriveNetworkError(f"Network error calling Drive API: {exc}") from exc


def _raise_for_status(response: requests.Response, context: str) -> None:
    """Raise the typed exception matching `response`'s status, or return if it's ok.

    403 gets its own type (DriveForbiddenError) since it means the
    folder isn't shared the way this pipeline expects — every other
    non-2xx status (404, 500, ...) is a generic DriveApiError.
    """

    if response.ok:
        return

    if response.status_code == 403:
        raise DriveForbiddenError(f"{context}: HTTP 403 Forbidden — {response.text}")

    raise DriveApiError(f"{context}: HTTP {response.status_code} — {response.text}")


def _stream_to_file(response: requests.Response, dest_path: Path) -> None:
    """Write a streamed response body to `dest_path`.

    A connection failure mid-stream is converted to DriveNetworkError
    and the partial file is removed — a half-written file must never
    be mistaken for a complete download.
    """

    try:
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                f.write(chunk)
    except requests.exceptions.RequestException as exc:
        dest_path.unlink(missing_ok=True)
        raise DriveNetworkError(f"Network error while downloading to {dest_path}: {exc}") from exc
