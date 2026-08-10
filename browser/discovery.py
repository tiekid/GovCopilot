"""One-off manual discovery script for inspecting the real VBĐH UI.

Not part of the application. Run directly to capture the current VBĐH
page (URL, title, HTML, accessibility snapshot, screenshot) using the
existing persistent login profile, for use in designing VBSearchAgent's
selectors against the real site.
"""

import logging
from pathlib import Path

from browser import BrowserSession

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("discovery")
_HTML_PATH = _OUTPUT_DIR / "home.html"
_SCREENSHOT_PATH = _OUTPUT_DIR / "home.png"
_INFO_PATH = _OUTPUT_DIR / "page_info.txt"


def run_discovery() -> None:
    """Open the persistent VBĐH session and capture the current page state."""

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    session = BrowserSession()

    try:
        page = session.open()

        current_url = page.url
        title = page.title()

        print(f"Current URL: {current_url}")
        print(f"Page title: {title}")

        logger.info("Capturing HTML for %s", current_url)
        _HTML_PATH.write_text(page.content(), encoding="utf-8")

        logger.info("Capturing full-page screenshot for %s", current_url)
        page.screenshot(path=str(_SCREENSHOT_PATH), full_page=True)

        info_lines = [f"Current URL: {current_url}", f"Page title: {title}", ""]

        try:
            snapshot = page.accessibility.snapshot()
        except Exception:
            logger.exception("Accessibility snapshot unavailable")
            snapshot = None

        if snapshot is not None:
            info_lines.append("Accessibility snapshot:")
            info_lines.append(str(snapshot))
        else:
            info_lines.append("Accessibility snapshot: unavailable")

        _INFO_PATH.write_text("\n".join(info_lines), encoding="utf-8")

        logger.info("Discovery output written to %s", _OUTPUT_DIR)

    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_discovery()
