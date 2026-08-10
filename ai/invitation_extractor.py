"""AI-based extraction of referenced documents from a meeting invitation.

This is the authoritative source for Meeting.documents. Regex-based
extraction (agents/document_extractor.py) is legacy and no longer
trusted for this purpose — it is kept only for comparison/benchmarking.

The actual model call is delegated to an AIProvider
(providers/ai_provider.py), selected by ProviderFactory
(providers/provider_factory.py) — this module owns everything
provider-agnostic: text normalization, prompt loading, JSON
parsing/validation, document-number normalization, deduplication, and
MeetingDocument construction. It never imports a specific provider
class or AI SDK, and never knows which provider is in use.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai.text_normalizer import normalize_document_identifiers
from models.document import MeetingDocument
from providers.ai_provider import AIProvider
from providers.provider_factory import create_provider

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "invitation_extraction.md"
_DEBUG_LOG_DIR = _PROJECT_ROOT / "logs" / "ai"


class AIInvitationExtractionError(Exception):
    """Raised when the AI response cannot be parsed into valid documents."""


class AIInvitationExtractor:
    """Extracts the authoritative list of referenced documents via AI.

    Debug artifacts (invitation text, prompt, raw response, parsed
    documents) are saved under logs/ai/<timestamp>/ for each call, for
    debugging and prompt improvement only — this is best-effort and
    never blocks or fails the actual extraction. No API keys,
    authorization headers, or other credentials are ever logged.
    """

    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self._provider = provider or create_provider()
        self._prompt = self._load_prompt()

    def extract_documents(self, text: str) -> List[MeetingDocument]:

        normalized_text = normalize_document_identifiers(text)

        logger.info(
            "Requesting AI document extraction (%d chars of invitation text) via %s/%s",
            len(normalized_text),
            self._provider.name,
            self._provider.model,
        )

        start = time.perf_counter()
        raw_content = self._provider.generate(self._prompt, normalized_text)
        latency_ms = (time.perf_counter() - start) * 1000

        documents = self._parse_documents(raw_content)

        self._save_debug_artifacts(normalized_text, raw_content, documents, latency_ms)

        logger.info(
            "AI extracted %d document(s) via %s/%s in %.0fms",
            len(documents),
            self._provider.name,
            self._provider.model,
            latency_ms,
        )

        return documents

    @staticmethod
    def _load_prompt() -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def _extract_json_object(self, raw_content: str) -> Dict[str, Any]:
        """Extract exactly one top-level JSON object from a raw model response.

        Tolerates surrounding non-JSON text (e.g. a model accidentally
        emitting commentary around the JSON), but fails fast rather
        than guessing when the response contains no JSON object or
        more than one, since either case means the response cannot be
        trusted to represent one unambiguous answer.
        """

        candidates = self._find_top_level_json_objects(raw_content)

        if not candidates:
            raise AIInvitationExtractionError("AI response contained no JSON object")

        if len(candidates) > 1:
            raise AIInvitationExtractionError(
                f"AI response contained {len(candidates)} top-level JSON objects; expected exactly one"
            )

        try:
            return json.loads(candidates[0])
        except json.JSONDecodeError as exc:
            raise AIInvitationExtractionError(f"AI response was not valid JSON: {exc}") from exc

    @staticmethod
    def _find_top_level_json_objects(raw_content: str) -> List[str]:
        """Return the raw text of every balanced top-level {...} span in raw_content.

        Braces inside JSON string literals (including escaped quotes)
        are not counted as structural, so a document number containing
        "{" or "}" cannot corrupt the scan.
        """

        objects: List[str] = []
        depth = 0
        start_index: Optional[int] = None
        in_string = False
        escape_next = False

        for index, char in enumerate(raw_content):

            if in_string:
                if escape_next:
                    escape_next = False
                elif char == "\\":
                    escape_next = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                if depth == 0:
                    start_index = index
                depth += 1
                continue

            if char == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start_index is not None:
                    objects.append(raw_content[start_index : index + 1])
                    start_index = None

        return objects

    def _parse_documents(self, raw_content: str) -> List[MeetingDocument]:

        payload = self._extract_json_object(raw_content)

        if not isinstance(payload, dict) or "documents" not in payload:
            raise AIInvitationExtractionError(
                "AI response JSON did not contain a 'documents' field"
            )

        raw_documents = payload["documents"]

        if not isinstance(raw_documents, list):
            raise AIInvitationExtractionError("AI response 'documents' field was not a list")

        documents: List[MeetingDocument] = []
        seen_numbers = set()

        for index, entry in enumerate(raw_documents):

            if not isinstance(entry, dict):
                raise AIInvitationExtractionError(
                    f"AI response document at index {index} was not an object"
                )

            number = self._normalize_number(entry.get("number", ""))

            if not number:
                raise AIInvitationExtractionError(
                    f"AI response document at index {index} had no document number"
                )

            if number in seen_numbers:
                continue

            seen_numbers.add(number)

            documents.append(MeetingDocument(number=number))

        return documents

    def _save_debug_artifacts(
        self,
        text: str,
        raw_content: str,
        documents: List[MeetingDocument],
        latency_ms: float,
    ) -> None:

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            run_dir = _DEBUG_LOG_DIR / timestamp
            run_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "invitation.txt").write_text(text, encoding="utf-8")
            (run_dir / "prompt.md").write_text(self._prompt, encoding="utf-8")
            (run_dir / "response.json").write_text(raw_content, encoding="utf-8")
            (run_dir / "documents.json").write_text(
                json.dumps(
                    [{"number": d.number} for d in documents],
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "provider": self._provider.name,
                        "model": self._provider.model,
                        "latency_ms": round(latency_ms, 1),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception:
            logger.warning("Failed to save AI extraction debug artifacts (non-fatal)", exc_info=True)

    @staticmethod
    def _normalize_number(value: object) -> str:
        """Strip all whitespace/line breaks — matches VBSearchAgent's document-number normalization."""

        if not isinstance(value, str):
            return ""

        return "".join(value.split())
