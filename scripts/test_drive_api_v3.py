"""Standalone confirmation test for Google Drive API v3 (API key, no OAuth).

Verifies, against the real Drive API, that:
  a. files.list can enumerate a shared folder's contents via an API key
     (no OAuth) using `'<FOLDER_ID>' in parents`.
  b. files.get?alt=media can download each file's original bytes.
  c. the size Drive's API reports matches the size actually downloaded.

This script is intentionally isolated from the production pipeline: it
does not import or modify DownloadAgent or anything under pipeline/.
It exists only to capture real API behavior before DownloadAgent is
changed (see CLAUDE.md: "Evidence before implementation").

Requires GOOGLE_DRIVE_API_KEY in .env (same load_dotenv() mechanism as
config.py: a plain API key restricted to the Google Drive API, created
for a folder shared as "Anyone with the link – reader").

Usage:
    python scripts/test_drive_api_v3.py [FOLDER_ID]

Defaults to the confirmed test folder "ND 13.4 - 9414" if no folder ID
is given on the command line.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Real Drive folder confirmed in the 2026-08-22 Cowork session: "ND 13.4 -
# 9414", a child of "TÀI LIỆU HỌP NGAY 24082026". Contains exactly 2 files
# (no zip) — used as the default test target when no folder ID is passed.
_DEFAULT_TEST_FOLDER_ID = "1UKjiiVRthPnOr08xpsSMtOxhy5pF23lu"

_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3/files"
_LIST_FIELDS = "files(id,name,mimeType,size)"
_REQUEST_TIMEOUT_SECONDS = 30
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "test_downloads"


class DriveApiTestError(Exception):
    """Raised when a Drive API call fails or returns an unusable response."""


def load_api_key() -> str:
    """Load GOOGLE_DRIVE_API_KEY from .env, mirroring config.py's load_dotenv() pattern."""

    load_dotenv()
    api_key = os.getenv("GOOGLE_DRIVE_API_KEY", "")

    if not api_key:
        raise DriveApiTestError("GOOGLE_DRIVE_API_KEY is not set in .env")

    return api_key


def list_files_in_folder(api_key: str, folder_id: str) -> List[Dict[str, Any]]:
    """Call files.list for `folder_id` and return the raw file entries."""

    logger.info("Listing files in folder %s via files.list", folder_id)

    response = requests.get(
        _DRIVE_API_BASE_URL,
        params={
            "q": f"'{folder_id}' in parents",
            "fields": _LIST_FIELDS,
            "key": api_key,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        raise DriveApiTestError(
            f"files.list failed: HTTP {response.status_code} — {response.text}"
        )

    files = response.json().get("files", [])
    logger.info("files.list returned %d file(s)", len(files))

    return files


def download_file(api_key: str, file_id: str, file_name: str, dest_dir: Path) -> Path:
    """Download `file_id`'s original bytes via files.get?alt=media into `dest_dir`."""

    dest_path = dest_dir / file_name
    logger.info("Downloading file %s ('%s') -> %s", file_id, file_name, dest_path)

    response = requests.get(
        f"{_DRIVE_API_BASE_URL}/{file_id}",
        params={"alt": "media", "key": api_key},
        timeout=_REQUEST_TIMEOUT_SECONDS,
        stream=True,
    )

    if not response.ok:
        raise DriveApiTestError(
            f"files.get?alt=media failed for {file_id}: "
            f"HTTP {response.status_code} — {response.text}"
        )

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
            f.write(chunk)

    return dest_path


def _report_row(file_entry: Dict[str, Any], actual_size_bytes: int) -> None:
    api_size = file_entry.get("size")
    api_size_bytes = int(api_size) if api_size is not None else None
    matches = api_size_bytes == actual_size_bytes

    print(f"  name:              {file_entry.get('name')}")
    print(f"  mimeType:          {file_entry.get('mimeType')}")
    print(f"  size (API):        {api_size_bytes}")
    print(f"  size (downloaded): {actual_size_bytes}")
    print(f"  match:             {'OK' if matches else 'MISMATCH'}")
    print()


def main() -> int:
    folder_id = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_TEST_FOLDER_ID

    try:
        api_key = load_api_key()
        files = list_files_in_folder(api_key, folder_id)
    except DriveApiTestError as exc:
        logger.error("%s", exc)
        return 1

    if not files:
        logger.warning("No files found in folder %s", folder_id)
        return 0

    print(f"\nfiles.list result for folder {folder_id}:")
    for file_entry in files:
        print(f"  - {file_entry}")
    print()

    _OUTPUT_DIR.mkdir(exist_ok=True)

    print("Download results:\n")
    for file_entry in files:
        file_id = file_entry["id"]
        file_name = file_entry["name"]

        try:
            dest_path = download_file(api_key, file_id, file_name, _OUTPUT_DIR)
        except DriveApiTestError as exc:
            logger.error("%s", exc)
            continue

        actual_size_bytes = dest_path.stat().st_size
        _report_row(file_entry, actual_size_bytes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
