"""Unit tests for ai/review.py's read-back of externally-produced reviews.

ReviewAgent never calls an AI provider or a browser — it only reads
NDxx.review.md files that some other, out-of-codebase workflow (Cowork
+ ChatGPT web) already wrote to disk. Uses real temp files, matching
this project's evidence-first testing style (see
tests/test_normalization_agent.py).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.normalization import NormalizedAgendaGroup
from ai.review import ReviewAgent


class ReviewAgentTests(unittest.TestCase):

    def test_reads_existing_review_file(self) -> None:
        with TemporaryDirectory() as reviews_dir:
            reviews = Path(reviews_dir)
            (reviews / "ND01.review.md").write_text("# Review nội dung 01", encoding="utf-8")

            group = NormalizedAgendaGroup(ma_nd="ND01", agenda_item_index=1)

            agent = ReviewAgent(reviews)
            results = agent.collect([group])

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].reviewed)
            self.assertEqual(results[0].review_content, "# Review nội dung 01")
            self.assertEqual(results[0].review_path, str(reviews / "ND01.review.md"))

    def test_missing_review_file_is_not_an_error(self) -> None:
        with TemporaryDirectory() as reviews_dir:
            group = NormalizedAgendaGroup(ma_nd="ND02", agenda_item_index=2)

            agent = ReviewAgent(Path(reviews_dir))

            with self.assertLogs("ai.review", level="INFO") as logs:
                results = agent.collect([group])

            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].reviewed)
            self.assertIsNone(results[0].review_content)
            self.assertIsNone(results[0].review_path)
            # Must be logged, but never as a WARNING — not yet reviewed
            # is a normal mid-workflow state.
            self.assertTrue(any("ND02" in message for message in logs.output))
            self.assertFalse(any(message.startswith("WARNING") for message in logs.output))

    def test_preserves_agenda_item_index_and_ma_nd(self) -> None:
        with TemporaryDirectory() as reviews_dir:
            group = NormalizedAgendaGroup(ma_nd="ND03", agenda_item_index=3)

            agent = ReviewAgent(Path(reviews_dir))
            result = agent.collect([group])[0]

            self.assertEqual(result.ma_nd, "ND03")
            self.assertEqual(result.agenda_item_index, 3)

    def test_mixed_reviewed_and_unreviewed_groups(self) -> None:
        with TemporaryDirectory() as reviews_dir:
            reviews = Path(reviews_dir)
            (reviews / "ND01.review.md").write_text("Reviewed", encoding="utf-8")

            groups = [
                NormalizedAgendaGroup(ma_nd="ND01", agenda_item_index=1),
                NormalizedAgendaGroup(ma_nd="ND02", agenda_item_index=2),
            ]

            agent = ReviewAgent(reviews)
            results = agent.collect(groups)

            by_ma_nd = {r.ma_nd: r for r in results}
            self.assertTrue(by_ma_nd["ND01"].reviewed)
            self.assertFalse(by_ma_nd["ND02"].reviewed)


if __name__ == "__main__":
    unittest.main()
