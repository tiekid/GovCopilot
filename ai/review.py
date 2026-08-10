"""Agent that collects AI review results produced outside this codebase.

By deliberate architecture decision, ReviewAgent never calls an AI
provider and never touches Playwright/a browser: the actual ChatGPT
analysis of each `NDxx.zip` bundle happens outside this Python app,
through a Cowork session — a human (or a separate, manual/semi-
automated workflow) runs the bundle through ChatGPT web and saves the
result as `NDxx.review.md` in a reviews directory. This avoids the
ToS risk of automating the ChatGPT web UI (see docs/ARCHITECTURE.md's
Hard rules for the full rationale).

ReviewAgent's only job is to read back whatever review files already
exist for a set of `NormalizedAgendaGroup`s produced by
`agents/normalization.py`, and report which groups are still waiting
on a review — a missing review file is a normal, expected mid-workflow
state, not an error.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from agents.normalization import NormalizedAgendaGroup

logger = logging.getLogger(__name__)


@dataclass
class ReviewedAgendaGroup:
    """Result of looking up one ND's externally-produced review file."""

    ma_nd: str
    agenda_item_index: Optional[int]
    review_path: Optional[str]
    review_content: Optional[str]
    reviewed: bool


class ReviewAgent:
    """Reads back AI review results already written to `reviews_dir`.

    Never calls an AI provider, never calls a browser — purely reads
    files from disk that some other, out-of-codebase workflow (Cowork +
    ChatGPT web) already produced.
    """

    def __init__(self, reviews_dir: Path) -> None:
        self._reviews_dir = reviews_dir

    def collect(self, groups: List[NormalizedAgendaGroup]) -> List[ReviewedAgendaGroup]:

        results: List[ReviewedAgendaGroup] = []

        for group in groups:
            review_path = self._reviews_dir / f"{group.ma_nd}.review.md"

            if review_path.exists():
                review_content = review_path.read_text(encoding="utf-8")
                reviewed = True
                logger.info("Found review for %s: %s", group.ma_nd, review_path)
            else:
                review_content = None
                reviewed = False
                logger.info(
                    "No review yet for %s (expected at %s) — not an error, "
                    "review may still be in progress",
                    group.ma_nd,
                    review_path,
                )

            results.append(
                ReviewedAgendaGroup(
                    ma_nd=group.ma_nd,
                    agenda_item_index=group.agenda_item_index,
                    review_path=str(review_path) if reviewed else None,
                    review_content=review_content,
                    reviewed=reviewed,
                )
            )

        reviewed_count = sum(1 for r in results if r.reviewed)
        logger.info(
            "Collected reviews for %d/%d agenda group(s)", reviewed_count, len(results)
        )

        return results
