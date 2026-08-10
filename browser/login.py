"""Reusable, persistent VBĐH browser session backed by Playwright.

BrowserSession launches and manages the persistent browser only. It
reports observable session state (e.g. whether the login screen is
currently visible) but never decides what to do with that information,
never performs login, and never makes workflow decisions — that is the
caller's responsibility (VBSearchAgent today; a GUI, CLI, MCP server,
or other API-driven caller may all use it the same way).
"""

import logging
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from config import VB_URL

logger = logging.getLogger(__name__)

_PROFILE_DIR = Path("profile")
_SLOW_MO_MS = 200

# Verified against real captured VBĐH login-page markup
# (discovery/home.html): the login form's fields and submit control.
_LOGIN_USERNAME_SELECTOR = 'input[name="username"]'
_LOGIN_PASSWORD_SELECTOR = 'input[name="password"]'
_LOGIN_BUTTON_SELECTOR = ".ui.submit.button"

# Verified real menu text shown only once a session is authenticated
# (also used by agents/vb_search.py) — used here purely as an
# infrastructure-level "is this an authenticated session" observation,
# same category as _is_login_screen_visible below, not business logic.
_AUTHENTICATED_MENU_TEXT = "Quản lý VB&ĐH"

# Automatic login: the browser's own saved-credential autofill (not
# GovCopilot) fills the username/password fields once the persistent
# profile's login form renders — this only waits for that to happen,
# never types credentials itself.
_AUTOFILL_TIMEOUT_MS = 5_000
_LOGIN_BUTTON_READY_TIMEOUT_MS = 5_000
_AUTH_CONFIRM_TIMEOUT_SECONDS = 15.0
_AUTH_POLL_INTERVAL_SECONDS = 0.5

# "One click per page load; if login reloads the page back to login,
# allow one more" — never more than this across one open() call.
_MAX_AUTOMATIC_LOGIN_CLICKS = 2


class SessionState(Enum):
    """Observable VBĐH session state, as reported by BrowserSession."""

    AUTHENTICATED = "AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"


class BrowserSession:
    """Manages a persistent, reusable Playwright browser session for VBĐH.

    Reuses the on-disk Playwright profile so a manual login, once
    captured, is carried across runs. Reports session state; never
    decides what to do with it.
    """

    def __init__(self, profile_dir: Path = _PROFILE_DIR, slow_mo_ms: int = _SLOW_MO_MS) -> None:
        self._profile_dir = profile_dir
        self._slow_mo_ms = slow_mo_ms
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    def open(self) -> Tuple[Page, SessionState]:
        """Open the persistent profile, navigate to VBĐH, and report session state.

        Idempotent: if a session is already open, reuses the existing
        page instead of creating a new browser context. Never blocks on
        console input — the caller decides what to do with the reported
        `SessionState`.
        """

        if self._context is not None:
            logger.info("BrowserSession already open; reusing existing session")
            page = self.get_page()
            return page, self._report_state()

        logger.info("Opening persistent VBĐH browser session at %s", self._profile_dir)

        self._playwright = sync_playwright().start()

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=False,
            slow_mo=self._slow_mo_ms,
        )

        page = self.get_page()

        # The one and only explicit navigation open() ever performs.
        # Automatic login (below) reacts to whatever page this lands
        # on — it never navigates itself, so it can never race this
        # goto() or start a second competing navigation.
        page.goto(VB_URL, wait_until="networkidle")

        if self._is_login_screen_visible():
            self._attempt_automatic_login(page)

        state = self._report_state()

        logger.info("VBĐH session opened with state: %s", state.value)

        return page, state

    def get_page(self) -> Page:
        """Return the active tab, reusing an existing one instead of opening a new tab."""

        if self._context is None:
            raise RuntimeError("BrowserSession is not open. Call open() first.")

        return self._context.pages[0] if self._context.pages else self._context.new_page()

    def wait_until_authenticated(
        self,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        """Block until the session is no longer showing the login screen.

        Infrastructure-level only: polls the same observation used by
        `open()` to report state. Performs no login, makes no workflow
        decisions — it only waits until the browser session is usable.
        Calling this is entirely the caller's choice.
        """

        start = time.monotonic()

        while self._is_login_screen_visible():
            if timeout_seconds is not None and (time.monotonic() - start) > timeout_seconds:
                raise TimeoutError("Timed out waiting for VBĐH authentication")

            time.sleep(poll_interval_seconds)

    def close(self) -> None:
        """Close the browser context and stop Playwright.

        Safe to call multiple times, including when no session is open.
        """

        if self._context is not None:
            logger.info("Closing VBĐH browser session")

            try:
                self._context.close()
            except Exception:
                logger.exception("Error while closing browser context")
            finally:
                self._context = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.exception("Error while stopping Playwright")
            finally:
                self._playwright = None

    def _report_state(self) -> SessionState:
        if self._is_login_screen_visible():
            return SessionState.LOGIN_REQUIRED

        return SessionState.AUTHENTICATED

    def _is_login_screen_visible(self) -> bool:
        """Report whether the VBĐH login form is currently visible.

        Infrastructure-level UI observation only — checks for the
        presence of the login form's username field. Verified against
        real captured VBĐH login-page markup. This is an implementation
        detail and may change without affecting BrowserSession's public
        API; it is the single place this check is implemented.
        """

        page = self.get_page()

        return page.locator(_LOGIN_USERNAME_SELECTOR).count() > 0

    def _attempt_automatic_login(self, page: Page) -> None:
        """Best-effort automatic login using the browser's own saved credentials.

        Never types a username or password — only waits for the
        persistent profile's own autofill to populate the form, then
        clicks the verified login button. Never navigates (see open()).
        At most _MAX_AUTOMATIC_LOGIN_CLICKS clicks total: one per page
        load, plus one more if login reloads back to the login screen —
        never more than that, regardless of outcome.

        If autofill never happens, or authentication still isn't
        confirmed after the allowed clicks, this simply returns without
        raising: the caller (open()) reports whatever state actually
        resulted, and the existing manual-login fallback
        (wait_until_authenticated()) still works unchanged.
        """

        for attempt in range(1, _MAX_AUTOMATIC_LOGIN_CLICKS + 1):

            if not self._is_login_screen_visible():
                logger.info("Automatic login: no longer on the login screen; nothing to do")
                return

            if not self._wait_for_login_autofill(page):
                logger.info("Automatic login: credentials were not autofilled; leaving login to the user")
                return

            button = page.locator(_LOGIN_BUTTON_SELECTOR)

            try:
                button.wait_for(state="visible", timeout=_LOGIN_BUTTON_READY_TIMEOUT_MS)
            except Exception:
                logger.info("Automatic login: login button never became visible; leaving login to the user")
                return

            if not button.is_enabled():
                logger.info("Automatic login: login button never became enabled; leaving login to the user")
                return

            logger.info(
                "Automatic login: clicking login button (attempt %d/%d)",
                attempt,
                _MAX_AUTOMATIC_LOGIN_CLICKS,
            )
            button.click()

            if self._wait_for_authentication_confirmed(page):
                logger.info("Automatic login: authentication confirmed")
                return

        logger.info(
            "Automatic login: authentication not confirmed after %d click(s); leaving login to the user",
            _MAX_AUTOMATIC_LOGIN_CLICKS,
        )

    def _wait_for_login_autofill(self, page: Page) -> bool:
        """Wait for the browser's own saved-credential autofill to populate the login form."""

        try:
            page.wait_for_function(
                "() => {"
                "  const u = document.querySelector('input[name=username]');"
                "  const p = document.querySelector('input[name=password]');"
                "  return !!(u && p && u.value && p.value);"
                "}",
                timeout=_AUTOFILL_TIMEOUT_MS,
            )
            return True
        except Exception:
            return False

    def _wait_for_authentication_confirmed(self, page: Page) -> bool:
        """Poll multiple real signals rather than relying on URL alone.

        Confirmed the moment ANY of: the login screen is gone, the
        authenticated menu is present, or the page has landed back on
        VB_URL (the home page).
        """

        deadline = time.monotonic() + _AUTH_CONFIRM_TIMEOUT_SECONDS

        while time.monotonic() < deadline:

            if not self._is_login_screen_visible():
                return True

            if page.get_by_text(_AUTHENTICATED_MENU_TEXT).count() > 0:
                return True

            if page.url.rstrip("/") == VB_URL.rstrip("/"):
                return True

            time.sleep(_AUTH_POLL_INTERVAL_SECONDS)

        return False

    def __enter__(self) -> "BrowserSession":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        self.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    session = BrowserSession()

    try:
        _, session_state = session.open()

        print(f"Session state: {session_state.value}")

        if session_state is SessionState.LOGIN_REQUIRED:
            print("Vui lòng đăng nhập thủ công trong cửa sổ trình duyệt đang mở.")
            print("Đang chờ đăng nhập...")
            session.wait_until_authenticated()
            print("Đã đăng nhập.")

        input("Nhấn Enter để đóng trình duyệt...")
    finally:
        session.close()
