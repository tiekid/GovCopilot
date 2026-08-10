"""Unit tests for agents/vb_search.py's no-match diagnostics (Bug 2).

FakePage-tier (docs/TESTING.md tier 2): exercises
_open_matching_result/_log_no_match_diagnostics with a minimal fake
result-cell locator — no real browser. Investigation instrumentation
only; VBSearchAgent's match/no-match outcome is unchanged.
"""

import json
import unittest
from typing import List

from agents.vb_search import VBSearchAgent, _SEARCH_DIAGNOSTICS_LOG_DIR
from models.document import MeetingDocument


class _FakeCell:
    def __init__(self, text: str) -> None:
        self._text = text
        self.clicked = False

    def inner_text(self) -> str:
        return self._text

    def wait_for(self, state=None, timeout=None) -> None:
        pass

    def click(self) -> None:
        self.clicked = True


class _FakeCellsLocator:
    def __init__(self, texts: List[str]) -> None:
        self._cells = [_FakeCell(t) for t in texts]

    def count(self) -> int:
        return len(self._cells)

    def nth(self, index: int) -> _FakeCell:
        return self._cells[index]


class _FakePage:
    def __init__(self, cells: _FakeCellsLocator) -> None:
        self._cells = cells

    def locator(self, _selector: str) -> _FakeCellsLocator:
        return self._cells

    def wait_for_timeout(self, _timeout_ms: int) -> None:
        pass


def _read_diagnostics(document_number: str) -> dict:
    sanitized = document_number.replace("/", "_")
    path = _SEARCH_DIAGNOSTICS_LOG_DIR / f"{sanitized}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class OpenMatchingResultDiagnosticsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.agent = VBSearchAgent(browser_session=None)  # not used by _open_matching_result

    def test_match_found_clicks_and_returns_true(self) -> None:
        document = MeetingDocument(number="8069/TTr-SYT")
        cells = _FakeCellsLocator(["1234/ABC-XYZ", "8069/TTr-SYT"])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertTrue(found)
        self.assertTrue(cells.nth(1).clicked)

    def test_no_match_logs_complete_diagnostics(self) -> None:
        document = MeetingDocument(number="TEST/NO-MATCH-001")
        cells = _FakeCellsLocator(["1234/ABC-XYZ", "5678/DEF-UVW"])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertFalse(found)

        diagnostics = _read_diagnostics(document.number)
        self.assertEqual(diagnostics["document_number"], "TEST/NO-MATCH-001")
        self.assertEqual(diagnostics["search_keyword"], "TEST/NO-MATCH-001")
        self.assertEqual(diagnostics["row_count"], 2)
        self.assertEqual(diagnostics["visible_row_count"], 2)
        self.assertEqual(diagnostics["first_visible_row_text"], "1234/ABC-XYZ")
        self.assertEqual(diagnostics["visible_row_texts"], ["1234/ABC-XYZ", "5678/DEF-UVW"])
        self.assertEqual(diagnostics["selector_used"], "td.so-hieu[ng-click=\"$p.showFormXuLyClick(item)\"]")
        self.assertEqual(diagnostics["network_response_status"], 200)

    def test_no_match_with_zero_rows_logs_empty_state(self) -> None:
        document = MeetingDocument(number="TEST/NO-MATCH-ZERO-ROWS")
        cells = _FakeCellsLocator([])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertFalse(found)

        diagnostics = _read_diagnostics(document.number)
        self.assertEqual(diagnostics["row_count"], 0)
        self.assertIsNone(diagnostics["first_visible_row_text"])
        self.assertEqual(diagnostics["visible_row_texts"], [])

    def test_matches_when_cell_has_leading_or_trailing_whitespace_on_the_number_line(self) -> None:
        document = MeetingDocument(number="9949/BC-STC")
        cells = _FakeCellsLocator([" 9949/BC-STC "])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertTrue(found)

    def test_matches_when_cell_has_urgency_annotation_on_a_second_line(self) -> None:
        # Bug 2 regression test — the real, evidenced root cause: VBĐH
        # appends an urgency annotation on a second line within the
        # same cell ("8069/TTr-SYT\nHỎA TỐC",
        # "9949/BC-STC\nHỎA TỐC HẸN GIỜ"), so comparing the whole
        # multi-line cell text against the bare document number never
        # matched, even though the row was right there.
        document = MeetingDocument(number="8069/TTr-SYT")
        cells = _FakeCellsLocator(["8069/TTr-SYT\nHỎA TỐC"])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertTrue(found)
        self.assertTrue(cells.nth(0).clicked)

    def test_matches_with_hen_gio_annotation_variant(self) -> None:
        document = MeetingDocument(number="9949/BC-STC")
        cells = _FakeCellsLocator(["9949/BC-STC\nHỎA TỐC HẸN GIỜ"])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertTrue(found)

    def test_does_not_match_a_different_number_that_merely_shares_a_second_line_annotation(self) -> None:
        # The fix must compare the first line only, not "does the cell
        # contain the target substring anywhere" — a different document
        # with the same annotation must still not match.
        document = MeetingDocument(number="8069/TTr-SYT")
        cells = _FakeCellsLocator(["9999/XX-YYY\nHỎA TỐC"])
        page = _FakePage(cells)

        found = self.agent._open_matching_result(page, document, response_status=200)

        self.assertFalse(found)


if __name__ == "__main__":
    unittest.main()
