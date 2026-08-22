"""Agent that downloads the attachment for an already-opened VBĐH document.

Assumes VBSearchAgent has already located and opened a matching
document (the #formXuLy modal) on the shared browser session. This
agent downloads the attachment for that document — including, when the
attachment section hasn't rendered, closing and reopening the SAME
document once (see "Attachment section reopen" below), which requires
an optional VBSearchAgent collaborator purely for that one step. It
never performs a fresh search, never navigates independently, and
never performs AI analysis.

Investigation instrumentation: every call to download() records the
complete observed state transition of the dialog — dialog/table
presence, attachment row count, download-control state, and what
actually happened after the click (download event / navigation / new
tab / iframe / the last network response's status and content-type) —
to logs/download/<document-number>.json.

Root cause, confirmed by real evidence (docs/09_LESSONS_LEARNED.md):
- The dialog contains SIX tables (attachments, forwarded comments,
  processing history ×2, receiving agency, a routing table) — every
  one of them independently shows "Không có dữ liệu" when empty, so
  checking that text anywhere in the dialog is true almost regardless
  of the attachment table's actual state. The real attachment table has
  a stable id, "tapTinDinhKem" ("tệp tin đính kèm" = attached files),
  captured from real markup — _inspect_dialog now targets that table
  specifically, never table.first, and "Không có dữ liệu" is only ever
  checked inside it.
- Each table's empty state is a `<tr class="noData">` placeholder row
  *inside* `<tbody>` — a naive `tbody tr` count therefore reports 1 row
  for a genuinely empty table. Excluded via `:not(.noData)`.
- Real-world confirmed: VBĐH sometimes opens the dialog without
  rendering the attachment section at all; closing and reopening the
  same document fixes it. download() now does exactly that, at most
  once, using attachment-table-exists / rows-exist / control-visible
  as the only retry signal — never "Không có dữ liệu" (see above), and
  never a download timeout (that's a different problem).
- Confirmed by a real multi-document E2E run: no exit path ever closed
  the dialog — not after a successful download, not after giving up on
  a still-incomplete reopen, not on an unexpected exception — which
  left it open and stalled every subsequent document's search for 30s
  in production. download() now guarantees the dialog is closed and
  hidden on every exit path via a single `finally`-block call (see
  _ensure_dialog_closed), instead of individual close calls scattered
  across specific branches.

Also exposes download_from_drive() — a second, independent download
path for documents whose source is a shared Google Drive folder rather
than VBĐH. It shares no Playwright state with download() (no browser
session, no dialog) and uses agents/drive_client.py for all Drive HTTP
calls; DownloadAgent itself owns the folder-traversal and
document-matching decisions (drive_client stays transport-only, same
split as providers/ for AI). Both paths return the same DownloadResult
and mutate MeetingDocument identically, so callers downstream
(NormalizationAgent, the pipeline) don't need to know which source a
document came from.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

from playwright.sync_api import Page, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config
from agents import drive_client
from browser.login import BrowserSession
from models.document import MeetingDocument

if TYPE_CHECKING:
    from agents.vb_search import VBSearchAgent

logger = logging.getLogger(__name__)

_DOWNLOAD_BUTTON_SELECTOR = ".ui.download"

# Verified against the real VBĐH system: the detail dialog opened by
# VBSearchAgent (see agents/vb_search.py).
_DIALOG_SELECTOR = "#formXuLy"

# Verified against real captured markup: the attachment table's own
# stable Angular component id ("tệp tin đính kèm" = attached files) —
# scoped to this table specifically, never the dialog's first <table>
# (the dialog has six; only this one is attachments).
_ATTACHMENT_TABLE_SELECTOR = "#tapTinDinhKem"

# Verified real VBĐH copy for an empty table's placeholder row.
_NO_DATA_TEXT = "Không có dữ liệu"

# Bound on the network-idle wait used only to observe whether the
# dialog has settled — not a sleep, and not a guess at "the" real
# completion signal: dialog_rendered is one diagnostic signal among
# several (table detected, row count, ...) collected so the real
# signal can be identified from evidence.
_DIALOG_RENDER_TIMEOUT_MS = 15_000

# Real, confirmed wait for the dialog to actually disappear before
# reopening — not a sleep.
_DIALOG_CLOSE_TIMEOUT_MS = 5_000

# Verified against the real VBĐH system: #formXuLy is itself the
# Semantic UI ".ui.modal" element (its own class list includes
# "modal"), and it carries a real, visible close icon — no separate
# ancestor lookup needed. Root cause of unreliable dialog dismissal
# (confirmed by a live, evidence-based investigation, 20 attempts at
# production's exact zero-added-delay close timing): while the modal's
# own open animation is still running, it carries an "animating" CSS
# class, and Escape sent during that window is silently dropped by
# Semantic UI (0/10 success while animating, 10/10 once the animation
# had finished) — a ~50-60% real-world failure rate matching what was
# observed in production. Clicking this real close button instead
# succeeded in all 10 zero-delay attempts regardless of animating
# state (Semantic UI's own click handler queues behind the animation
# rather than dropping the request — some attempts simply took longer,
# never failed) — so _close_dialog() clicks it instead of pressing
# Escape.
_DIALOG_CLOSE_BUTTON_SELECTOR = "#formXuLy .close.icon:visible"

_DIAGNOSTICS_LOG_DIR = Path("logs") / "download"

# Adaptive download timeout — unchanged. VBĐH builds a ZIP archive
# server-side before a multi-attachment download starts; 30s base + 5s
# per attachment, capped at 120s.
_BASE_DOWNLOAD_TIMEOUT_SECONDS = 30
_PER_ATTACHMENT_TIMEOUT_SECONDS = 5
_MAX_DOWNLOAD_TIMEOUT_SECONDS = 120

_DOWNLOAD_TIMEOUT_MESSAGE = "VBĐH did not finish generating the download within the timeout."
_INCOMPLETE_DIALOG_MESSAGE = (
    "Detail dialog was incomplete (attachment table or download control not ready)."
)

# Drive path — unrelated to the VBĐH dialog constants above.
_DRIVE_MISSING_API_KEY_MESSAGE = "Google Drive API key is not configured (GOOGLE_DRIVE_API_KEY)."

# The only pattern confirmed by real evidence so far (scripts/test_drive_api_v3.py,
# docs/GovCopilot-v2-kien-truc.md): a document number like "9414/TTr-SXD"
# and its Drive file "9414_TTr-SXD_...pdf" share the same leading digit
# sequence. Anchored to the start of the string deliberately — a number
# embedded mid-string elsewhere in a filename would be a coincidence,
# not a real match.
_DRIVE_NUMBER_PREFIX_PATTERN = re.compile(r"\d+")


@dataclass
class DownloadDiagnostics:
    """Complete observed state transition of the detail dialog for one document.

    Investigation-only: captures what actually happens in the browser
    so real failure modes can be diagnosed from evidence instead of
    guessed. Written to logs/download/<document-number>.json for every
    document DownloadAgent.download() is called for, regardless of
    whether the download succeeds.
    """

    document_number: str
    dialog_opened: bool = False
    dialog_rendered: bool = False
    attachment_table_detected: bool = False
    attachment_row_count: int = 0
    no_data_present: bool = False
    download_control_present: bool = False
    download_control_visible: bool = False
    download_control_enabled: bool = False
    reopened_dialog: bool = False
    download_click_performed: bool = False
    download_event_received: bool = False
    navigation_occurred: bool = False
    new_tab_opened: bool = False
    url_before_click: str = ""
    url_after_click: str = ""
    new_tab_url: Optional[str] = None
    iframe_count: int = 0
    last_response_url: Optional[str] = None
    last_response_status: Optional[int] = None
    last_response_content_type: Optional[str] = None
    error: Optional[str] = None


@dataclass
class DownloadResult:
    """Outcome of downloading the attachment for one MeetingDocument."""

    document: MeetingDocument
    success: bool
    local_path: Optional[str] = None
    error: Optional[str] = None


class DownloadAgent:
    """Downloads a document's attachment from VBĐH or from Google Drive.

    download() never performs a fresh search and never performs AI
    analysis. When the attachment section looks incomplete, it closes
    the dialog and reopens the same document exactly once, via the
    optional `vb_search_agent` collaborator — the only VBSearchAgent
    capability it reuses, and only for that one step.

    download_from_drive() is a separate, Playwright-independent path
    for documents sourced from a shared Google Drive folder — see the
    module docstring.
    """

    def __init__(
        self,
        browser_session: BrowserSession,
        download_dir: Path,
        vb_search_agent: Optional["VBSearchAgent"] = None,
        drive_api_key: Optional[str] = None,
    ) -> None:
        self._browser_session = browser_session
        self._download_dir = download_dir
        self._vb_search_agent = vb_search_agent

        # Reads config.* at call time (not import time), same reasoning
        # as GeminiProvider.__init__ — a runtime config change takes
        # effect on the next DownloadAgent construction, no restart.
        self._drive_api_key = drive_api_key if drive_api_key is not None else config.GOOGLE_DRIVE_API_KEY

    def download(
        self,
        document: MeetingDocument,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> DownloadResult:

        def report(message: str) -> None:
            logger.info(message)
            if progress_callback is not None:
                progress_callback(message)

        page = self._browser_session.get_page()

        logger.info("Downloading attachment for document number %s", document.number)

        diagnostics = DownloadDiagnostics(document_number=document.number)
        new_tabs: List[Page] = []
        navigations: List[str] = []
        responses: List[Response] = []

        def on_new_page(new_page: Page) -> None:
            new_tabs.append(new_page)

        def on_frame_navigated(frame: object) -> None:
            if frame == page.main_frame:
                navigations.append(page.url)

        def on_response(response: Response) -> None:
            responses.append(response)

        page.context.on("page", on_new_page)
        page.on("framenavigated", on_frame_navigated)
        page.on("response", on_response)

        try:
            self._download_dir.mkdir(parents=True, exist_ok=True)

            self._inspect_dialog(page, diagnostics)

            if self._is_attachment_section_incomplete(diagnostics) and self._vb_search_agent is not None:
                report("Attachment section missing.")

                if self._reopen_dialog(page, document, report):
                    diagnostics.reopened_dialog = True
                    self._inspect_dialog(page, diagnostics)

                    if not self._is_attachment_section_incomplete(diagnostics):
                        report("Attachment section detected.")

            if self._is_attachment_section_incomplete(diagnostics):
                logger.warning(
                    "Attachment section still incomplete for document number %s after reopen=%s "
                    "(attachment_table_detected=%s, attachment_row_count=%d, download_control_visible=%s)",
                    document.number,
                    diagnostics.reopened_dialog,
                    diagnostics.attachment_table_detected,
                    diagnostics.attachment_row_count,
                    diagnostics.download_control_visible,
                )
                diagnostics.error = _INCOMPLETE_DIALOG_MESSAGE
                return DownloadResult(
                    document=document, success=False, local_path=None, error=_INCOMPLETE_DIALOG_MESSAGE
                )

            report("Downloading...")

            diagnostics.url_before_click = page.url

            timeout_ms = self._compute_download_timeout_ms(diagnostics.attachment_row_count)

            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    diagnostics.download_click_performed = True
                    page.locator(_DOWNLOAD_BUTTON_SELECTOR).click()
            except PlaywrightTimeoutError:
                logger.warning(
                    "Download timed out for document number %s after %.0fs "
                    "(attachment_row_count=%d)",
                    document.number,
                    timeout_ms / 1000,
                    diagnostics.attachment_row_count,
                )
                diagnostics.error = _DOWNLOAD_TIMEOUT_MESSAGE
                return DownloadResult(
                    document=document, success=False, local_path=None, error=_DOWNLOAD_TIMEOUT_MESSAGE
                )

            diagnostics.download_event_received = True

            download = download_info.value

            saved_path = self._download_dir / download.suggested_filename
            download.save_as(saved_path)

            document.downloaded = True
            document.local_path = str(saved_path)

            logger.info("Saved document number %s to %s", document.number, saved_path)

            return DownloadResult(
                document=document,
                success=True,
                local_path=str(saved_path),
                error=None,
            )

        except Exception as exc:
            diagnostics.error = str(exc)
            logger.exception("Download failed for document number %s", document.number)
            return DownloadResult(document=document, success=False, local_path=None, error=str(exc))

        finally:
            page.context.remove_listener("page", on_new_page)
            page.remove_listener("framenavigated", on_frame_navigated)
            page.remove_listener("response", on_response)

            diagnostics.new_tab_opened = len(new_tabs) > 0
            diagnostics.new_tab_url = new_tabs[0].url if new_tabs else None
            diagnostics.url_after_click = page.url
            diagnostics.navigation_occurred = (
                len(navigations) > 0 or diagnostics.url_after_click != diagnostics.url_before_click
            )

            try:
                diagnostics.iframe_count = max(len(page.frames) - 1, 0)
            except Exception:
                diagnostics.iframe_count = 0

            if responses:
                last_response = responses[-1]
                try:
                    diagnostics.last_response_url = last_response.url
                    diagnostics.last_response_status = last_response.status
                    diagnostics.last_response_content_type = last_response.headers.get("content-type")
                except Exception:
                    pass

            self._save_diagnostics(diagnostics)

            # Guarantee: no exit path (success, timeout, still-incomplete,
            # or any exception) leaves the dialog open — see module
            # docstring. Runs after diagnostics capture so closing the
            # dialog can't affect what was recorded about the download
            # attempt itself.
            self._ensure_dialog_closed(page, document)

    def _inspect_dialog(self, page: Page, diagnostics: DownloadDiagnostics) -> None:
        """Populate every diagnostic signal observable before the download click.

        Never raises: an observation that fails (e.g. a selector that
        doesn't apply on a given page state) is recorded as a negative
        result, not an error — only the download attempt itself can
        fail the overall call.
        """

        dialog = page.locator(_DIALOG_SELECTOR)

        diagnostics.dialog_opened = dialog.count() > 0 and dialog.first.is_visible()

        if not diagnostics.dialog_opened:
            return

        try:
            page.wait_for_load_state("networkidle", timeout=_DIALOG_RENDER_TIMEOUT_MS)
            diagnostics.dialog_rendered = True
        except Exception:
            diagnostics.dialog_rendered = False

        attachment_table = dialog.locator(_ATTACHMENT_TABLE_SELECTOR)
        diagnostics.attachment_table_detected = attachment_table.count() > 0

        if diagnostics.attachment_table_detected:
            # Excludes the "noData" placeholder row itself — its own
            # empty-state <tr> is inside <tbody>, so an unfiltered
            # count reports 1 row for a genuinely empty table.
            diagnostics.attachment_row_count = attachment_table.locator("tbody tr:not(.noData)").count()
            diagnostics.no_data_present = attachment_table.get_by_text(_NO_DATA_TEXT).count() > 0
        else:
            diagnostics.attachment_row_count = 0
            diagnostics.no_data_present = False

        control = page.locator(_DOWNLOAD_BUTTON_SELECTOR)
        diagnostics.download_control_present = control.count() > 0

        if diagnostics.download_control_present:
            diagnostics.download_control_visible = control.first.is_visible()
            diagnostics.download_control_enabled = control.first.is_enabled()
        else:
            diagnostics.download_control_visible = False
            diagnostics.download_control_enabled = False

    @staticmethod
    def _is_attachment_section_incomplete(diagnostics: DownloadDiagnostics) -> bool:
        """Does the attachment section look like it hasn't finished rendering?

        Depends only on: the attachment table existing, having rows,
        and the download control being visible — confirmed real
        symptoms of VBĐH's attachment section rendering incompletely,
        fixed by closing and reopening the same document. Deliberately
        never depends on "Không có dữ liệu" (no_data_present): real
        evidence showed that text present in six different, mostly
        unrelated tables in the same dialog — checking it anywhere in
        the dialog was true almost regardless of the attachment table's
        actual state. It's still recorded (scoped to the attachment
        table now) for diagnostics, just never used for this decision.
        """

        if not diagnostics.attachment_table_detected:
            return True

        if diagnostics.attachment_row_count == 0:
            return True

        if not diagnostics.download_control_present:
            return True

        if not diagnostics.download_control_visible:
            return True

        return False

    def _reopen_dialog(
        self, page: Page, document: MeetingDocument, report: Callable[[str], None]
    ) -> bool:
        """Close the current dialog and reopen the same document, once.

        Returns whether the reopen (search + click the same row again)
        succeeded mechanically — this does not by itself guarantee the
        attachment section is now complete; the caller re-inspects
        afterward to check that.
        """

        report("Closing dialog...")
        self._ensure_dialog_closed(page, document)

        report("Reopening document...")

        try:
            reopened = self._vb_search_agent.search(document)
        except Exception:
            logger.exception("Failed to reopen document number %s", document.number)
            return False

        return bool(reopened.success and reopened.found)

    @staticmethod
    def _close_dialog(page: Page) -> None:
        """Close the detail dialog via its real close button.

        See _DIALOG_CLOSE_BUTTON_SELECTOR for the root-cause evidence
        behind using this instead of Escape. Bounded to
        _DIALOG_CLOSE_TIMEOUT_MS (the same bound _reopen_dialog already
        applies to confirming the dialog is hidden afterward) rather
        than Playwright's default click timeout, so a button that never
        becomes clickable can't stall this single attempt. Never
        raises: a failed close attempt shouldn't turn a reportable
        failure into an unrelated crash — the reopen that follows will
        simply find whatever state actually exists.
        """

        try:
            page.locator(_DIALOG_CLOSE_BUTTON_SELECTOR).click(timeout=_DIALOG_CLOSE_TIMEOUT_MS)
        except Exception:
            logger.warning("Failed to close detail dialog (non-fatal)", exc_info=True)

    def _ensure_dialog_closed(self, page: Page, document: MeetingDocument) -> None:
        """Close the dialog and confirm it's hidden — the single shared
        mechanism both the mid-flow reopen step and download()'s final
        exit guarantee use, so there's exactly one place implementing
        "close, then wait for hidden" (see module docstring's E2E
        finding: no path ever did this before, which stalled every
        subsequent document's search).

        A cheap existence/visibility check comes first so a document
        that never had a dialog open (or whose dialog is already
        hidden) doesn't pay _DIALOG_CLOSE_TIMEOUT_MS for nothing.
        Never raises.
        """

        dialog = page.locator(_DIALOG_SELECTOR)

        try:
            if dialog.count() == 0 or not dialog.first.is_visible():
                return
        except Exception:
            return

        self._close_dialog(page)

        try:
            dialog.wait_for(state="hidden", timeout=_DIALOG_CLOSE_TIMEOUT_MS)
        except Exception:
            logger.warning(
                "Detail dialog did not confirm closed for document number %s (continuing anyway)",
                document.number,
            )

    def _save_diagnostics(self, diagnostics: DownloadDiagnostics) -> None:

        try:
            _DIAGNOSTICS_LOG_DIR.mkdir(parents=True, exist_ok=True)

            log_path = _DIAGNOSTICS_LOG_DIR / f"{self._sanitize_filename(diagnostics.document_number)}.json"

            log_path.write_text(
                json.dumps(asdict(diagnostics), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            logger.info(
                "Wrote download diagnostics for document number %s to %s",
                diagnostics.document_number,
                log_path,
            )

        except Exception:
            logger.warning("Failed to save download diagnostics (non-fatal)", exc_info=True)

    @staticmethod
    def _compute_download_timeout_ms(attachment_row_count: int) -> int:
        """Adaptive expect_download() timeout, scaled by attachment count.

        30s base + 5s per attachment, capped at 120s — unchanged.
        """

        seconds = min(
            _BASE_DOWNLOAD_TIMEOUT_SECONDS
            + _PER_ATTACHMENT_TIMEOUT_SECONDS * attachment_row_count,
            _MAX_DOWNLOAD_TIMEOUT_SECONDS,
        )

        return seconds * 1000

    @staticmethod
    def _sanitize_filename(document_number: str) -> str:
        """Replace filesystem-unsafe characters (document numbers contain '/')."""

        sanitized = re.sub(r'[\\/:*?"<>|]', "_", document_number).strip()

        return sanitized or "unknown"

    # ------------------------------------------------------------------
    # Google Drive path — independent of everything above (no
    # Playwright, no dialog, no VBSearchAgent). See module docstring.
    # ------------------------------------------------------------------

    def download_from_drive(
        self,
        document: MeetingDocument,
        folder_id: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> DownloadResult:
        """Download `document`'s attachment from a shared Google Drive folder.

        `folder_id` may be either an ND subfolder that already contains
        files directly (the case confirmed by real evidence), or a
        parent meeting folder whose direct children are ND subfolders —
        both shapes are listed and reconciled by
        _list_drive_folder_recursive, exactly one level deep. Which
        folder_id to pass (and matching an ND subfolder to
        MeetingDocument.agenda_item_index) is the caller's
        responsibility — not yet resolved anywhere in this pipeline,
        see docs/GovCopilot-v2-kien-truc.md and the plan this method
        was implemented from.

        Mutates `document` and returns DownloadResult identically to
        download() on success — callers never need to know which
        source a document came from.
        """

        def report(message: str) -> None:
            logger.info(message)
            if progress_callback is not None:
                progress_callback(message)

        if not self._drive_api_key:
            logger.error(
                "Cannot download document number %s from Drive: no API key configured",
                document.number,
            )
            return DownloadResult(
                document=document, success=False, local_path=None, error=_DRIVE_MISSING_API_KEY_MESSAGE
            )

        logger.info("Downloading document number %s from Drive folder %s", document.number, folder_id)

        try:
            self._download_dir.mkdir(parents=True, exist_ok=True)

            files = self._list_drive_folder_recursive(folder_id, document.number)
            matches = self._match_drive_files(document.number, files)

            if not matches:
                message = (
                    f"No file matching document number '{document.number}' "
                    f"found in Drive folder '{folder_id}'."
                )
                logger.warning(message)
                return DownloadResult(document=document, success=False, local_path=None, error=message)

            if len(matches) > 1:
                message = (
                    f"Multiple files matched document number '{document.number}' "
                    f"in Drive folder '{folder_id}': {', '.join(m.name for m in matches)}."
                )
                logger.warning(message)
                return DownloadResult(document=document, success=False, local_path=None, error=message)

            file_entry = matches[0]
            report(f"Downloading '{file_entry.name}' from Drive...")

            saved_path = self._save_drive_file(file_entry)

            document.downloaded = True
            document.local_path = str(saved_path)

            logger.info("Saved document number %s to %s (from Drive)", document.number, saved_path)

            return DownloadResult(document=document, success=True, local_path=str(saved_path), error=None)

        except drive_client.DriveForbiddenError as exc:
            logger.error("Drive permission denied for document number %s: %s", document.number, exc)
            return DownloadResult(
                document=document, success=False, local_path=None, error=f"[Drive permission denied] {exc}"
            )

        except drive_client.DriveNetworkError as exc:
            logger.warning("Drive network error for document number %s: %s", document.number, exc)
            return DownloadResult(
                document=document, success=False, local_path=None, error=f"[Drive network error] {exc}"
            )

        except drive_client.DriveApiError as exc:
            logger.error("Drive API error for document number %s: %s", document.number, exc)
            return DownloadResult(
                document=document, success=False, local_path=None, error=f"[Drive API error] {exc}"
            )

        except Exception as exc:
            logger.exception("Unexpected failure downloading document number %s from Drive", document.number)
            return DownloadResult(document=document, success=False, local_path=None, error=str(exc))

    def _list_drive_folder_recursive(
        self, folder_id: str, document_number: str
    ) -> List[drive_client.DriveFileEntry]:
        """List `folder_id`, recursing exactly one level into any subfolders found.

        Handles both calling shapes confirmed by real evidence: an ND
        folder whose direct children are all files, and a parent
        meeting folder whose direct children are all ND subfolders.
        Files found directly at this level are included alongside
        files collected from one level of subfolders — real evidence
        so far shows each level is pure (all-files or all-folders), but
        nothing here assumes that has to stay true. Never recurses past
        one level: a folder found inside a subfolder is unexpected
        structure, logged and skipped rather than silently traversed.
        """

        entries = drive_client.list_folder(self._drive_api_key, folder_id)

        files = [entry for entry in entries if not drive_client.is_folder(entry.mime_type)]
        subfolders = [entry for entry in entries if drive_client.is_folder(entry.mime_type)]

        for subfolder in subfolders:
            sub_entries = drive_client.list_folder(self._drive_api_key, subfolder.id)

            for sub_entry in sub_entries:
                if drive_client.is_folder(sub_entry.mime_type):
                    logger.warning(
                        "Skipping unexpected nested folder '%s' inside '%s' while resolving "
                        "document number %s (only one level of subfolder is traversed)",
                        sub_entry.name,
                        subfolder.name,
                        document_number,
                    )
                    continue

                files.append(sub_entry)

        return files

    @staticmethod
    def _match_drive_files(
        document_number: str, files: List[drive_client.DriveFileEntry]
    ) -> List[drive_client.DriveFileEntry]:
        """Match `document_number` against candidate Drive files by its leading digit sequence.

        See _DRIVE_NUMBER_PREFIX_PATTERN — unverified across the full
        real ND dataset (confirmed for exactly one document so far), so
        callers must treat zero or multiple matches as a normal,
        reportable failure rather than assuming this heuristic is
        infallible.
        """

        prefix_match = _DRIVE_NUMBER_PREFIX_PATTERN.match(document_number.strip())

        if prefix_match is None:
            return []

        token = prefix_match.group(0)

        return [file_entry for file_entry in files if token in file_entry.name]

    def _save_drive_file(self, file_entry: drive_client.DriveFileEntry) -> Path:
        """Download or export `file_entry` into self._download_dir, returning the saved path.

        Native Google files (Docs/Sheets/Slides) have no binary content
        and must go through files.export instead of files.get?alt=media
        — see agents/drive_client.py. That path is implemented but not
        yet exercised against a real native file (none observed in any
        real ND folder so far), so the first real occurrence is logged
        distinctly for manual confirmation rather than trusted silently.
        """

        if drive_client.is_native_google_file(file_entry.mime_type):
            logger.warning(
                "Native Google file encountered: '%s' (mimeType=%s) — exporting via "
                "files.export, an unverified path (see agents/drive_client.py)",
                file_entry.name,
                file_entry.mime_type,
            )

            export_mime_type, extension = drive_client.resolve_export_target(file_entry.mime_type)
            saved_path = self._download_dir / f"{self._sanitize_filename(file_entry.name)}{extension}"

            drive_client.export_native_file(self._drive_api_key, file_entry.id, export_mime_type, saved_path)

        else:
            saved_path = self._download_dir / self._sanitize_filename(file_entry.name)

            drive_client.download_binary(self._drive_api_key, file_entry.id, saved_path)

        return saved_path
