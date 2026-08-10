"""Deterministic text normalization applied before AI extraction.

Merges Vietnamese government document identifiers that PDF/DOCX text
extraction has wrapped across a line break — e.g. a trailing
"9365/STC-" followed by "ĐTC" on the next line becomes
"9365/STC-ĐTC". This is pure text repair, not semantic interpretation,
so it runs before the text ever reaches the AI model: the model should
solve semantic extraction, not formatting cleanup.
"""

import re

_VN_UPPER = "A-ZĐÂÊÔƠƯ"

_WRAPPED_DOCUMENT_NUMBER_PATTERN = re.compile(
    rf"(\d+/[{_VN_UPPER}]+(?:-[{_VN_UPPER}]+)*-)\s*\r?\n\s*([{_VN_UPPER}]+)"
)


def normalize_document_identifiers(text: str) -> str:
    """Merge document identifiers wrapped across a line break into one token.

    Applied to a fixed point so every wrapped identifier in the text
    is merged, however many occurrences there are.
    """

    normalized = text
    previous = None

    while normalized != previous:
        previous = normalized
        normalized = _WRAPPED_DOCUMENT_NUMBER_PATTERN.sub(r"\1\2", normalized)

    return normalized
