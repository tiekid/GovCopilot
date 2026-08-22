"""AI-based faithful content extraction for one ND (agenda item) bundle.

First tier of the two-tier AI review architecture locked in
docs/GovCopilot-v2-kien-truc.md §3.2: this extracts each ND's content
faithfully — no summarizing, no analysis, no opinion — so a human +
Claude can analyze the extraction in a 6-section framework afterward
(ReviewAgent, unchanged, still just reads back that externally-produced
result). NDContentExtractor never does that second-tier analysis
itself.

Consumes NormalizationAgent's real output directly: NormalizedAgendaGroup.zip_path
(the actual, current file list — never meta.json's danh_sach_file,
which can drift from what's really in the zip) and .meta_path (read
only for prompt context: co_quan_trinh/ky_hop). Reuses
parser/invitation_reader.read_invitation() for PDF/DOCX text — the one
shared parsing implementation in the codebase (see
docs/ARCHITECTURE.md's hard rules) — never implements its own parsing.

Scope, matching real measured evidence (docs/GovCopilot-v2-kien-truc.md
§4): only ND bundles where every file has a real text layer readable
via pypdf/python-docx (~22/27 in the measured dataset). A scanned PDF
(0 extractable characters), an unsupported file type (e.g. .xlsx,
.zip — see docs/10_ADR.md's ADR-012 for real evidence these exist in
Drive-sourced folders), or a missing/empty bundle all skip the ND
entirely — per-ND, all-or-nothing, by deliberate v1 design (see
ADR-012): a loudly-skipped ND is safer than a silently incomplete one.
A skip never raises; it's always reported as data
(NDExtractionResult.skip_reason), so one bad ND never aborts a batch —
same reasoning as agents/download.py's DownloadResult.

Uses the exact same AIProvider protocol and provider_factory.create_provider()
as AIInvitationExtractor — but does zero response parsing: the
provider's raw text (stripped) *is* the output file's content, since
this is free-text extraction, not JSON-structured extraction.
"""

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from agents.normalization import NormalizedAgendaGroup
from parser.invitation_reader import read_invitation
from providers.ai_provider import AIProvider
from providers.provider_factory import create_provider

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "nd_extraction.md"


@dataclass
class NDExtractionResult:
    """Outcome of extracting one ND's content."""

    ma_nd: str
    agenda_item_index: Optional[int]
    extract_path: Optional[str]
    extracted: bool
    skip_reason: Optional[str] = None


class NDContentExtractor:
    """Extracts faithful, non-summarized content from each ND bundle via AI."""

    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self._provider = provider or create_provider()
        self._prompt = self._load_prompt()

    def extract(self, groups: List[NormalizedAgendaGroup]) -> List[NDExtractionResult]:
        return [self._extract_one(group) for group in groups]

    def _extract_one(self, group: NormalizedAgendaGroup) -> NDExtractionResult:

        zip_path = Path(group.zip_path)

        if not zip_path.exists():
            return self._skip(group, f"Bundle not found: {zip_path.name}")

        try:
            sections = self._read_bundle_sections(group, zip_path)
        except _SkipND as skip:
            return self._skip(group, skip.reason)
        except Exception as exc:
            logger.exception("Unexpected failure reading bundle for %s", group.ma_nd)
            return self._skip(group, f"Failed to read bundle: {exc}")

        if sections is None:
            return self._skip(group, "Bundle contains no files")

        user_prompt = self._build_user_prompt(group, sections)

        logger.info(
            "Requesting AI content extraction for %s (%d file(s)) via %s/%s",
            group.ma_nd,
            len(sections),
            self._provider.name,
            self._provider.model,
        )

        try:
            raw_text = self._provider.generate(self._prompt, user_prompt)
        except Exception as exc:
            logger.error("AI provider failed for %s: %s", group.ma_nd, exc)
            return self._skip(group, f"AI provider error: {exc}")

        extract_path = zip_path.parent / f"{group.ma_nd}.extract.md"
        extract_path.write_text(raw_text.strip() + "\n", encoding="utf-8")

        logger.info("Wrote extraction for %s to %s", group.ma_nd, extract_path)

        return NDExtractionResult(
            ma_nd=group.ma_nd,
            agenda_item_index=group.agenda_item_index,
            extract_path=str(extract_path),
            extracted=True,
        )

    @staticmethod
    def _read_bundle_sections(
        group: NormalizedAgendaGroup, zip_path: Path
    ) -> Optional[List[tuple]]:
        """Return [(filename, text), ...] for every file in the zip, or
        None if the zip has no files at all.

        Reads the zip's real namelist() — never meta.json's
        danh_sach_file, which can list a file no longer actually in the
        zip (see docs/GovCopilot-v2-kien-truc.md investigation).
        Raises _SkipND for any condition that should skip the whole ND
        (unsupported type, unreadable file, scanned/empty file) — the
        caller converts that into a normal NDExtractionResult, never a
        crash.
        """

        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()

            if not names:
                return None

            sections = []

            with TemporaryDirectory() as tmp_dir:
                for name in names:
                    extracted_path = Path(tmp_dir) / Path(name).name

                    with archive.open(name) as source, open(extracted_path, "wb") as dest:
                        dest.write(source.read())

                    try:
                        text = read_invitation(str(extracted_path))
                    except ValueError:
                        raise _SkipND(f"Unsupported file type: '{name}'")
                    except Exception as exc:
                        raise _SkipND(f"Failed to read '{name}': {exc}")

                    if not text.strip():
                        raise _SkipND(
                            f"'{name}' has no extractable text (likely a scanned PDF)"
                        )

                    sections.append((name, text))

            return sections

    @staticmethod
    def _build_user_prompt(group: NormalizedAgendaGroup, sections: List[tuple]) -> str:

        co_quan_trinh = ""
        ky_hop = ""

        meta_path = Path(group.meta_path)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                co_quan_trinh = meta.get("co_quan_trinh", "")
                ky_hop = meta.get("ky_hop", "")
            except Exception:
                logger.warning("Failed to read %s for prompt context (non-fatal)", meta_path)

        header = f"Mã ND: {group.ma_nd}\nCơ quan trình: {co_quan_trinh}\nKỳ họp: {ky_hop}"

        file_blocks = [f"=== Tệp: {name} ===\n{text}" for name, text in sections]

        return "\n\n".join([header, *file_blocks])

    @staticmethod
    def _skip(group: NormalizedAgendaGroup, reason: str) -> NDExtractionResult:
        logger.warning("Skipping %s: %s", group.ma_nd, reason)
        return NDExtractionResult(
            ma_nd=group.ma_nd,
            agenda_item_index=group.agenda_item_index,
            extract_path=None,
            extracted=False,
            skip_reason=reason,
        )

    @staticmethod
    def _load_prompt() -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")


class _SkipND(Exception):
    """Internal signal: skip the whole ND for `reason` — never raised past this module."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
