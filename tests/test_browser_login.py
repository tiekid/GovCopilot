"""Unit tests for browser/login.py's automatic login flow.

Exercises BrowserSession._attempt_automatic_login and its helpers
directly via a minimal fake page — never launches a real browser. A
thin subclass overrides get_page() so these tests never need a real
Playwright context (BrowserSession's public API is untouched; only its
private, always-injectable get_page() is overridden here for testing).
"""

import unittest
from typing import List, Optional
from unittest.mock import patch

import browser.login as login_module
from browser.login import BrowserSession, _MAX_AUTOMATIC_LOGIN_CLICKS


class _FakeButton:
    def __init__(self, page: "_FakeLoginPage", visible: bool, enabled: bool) -> None:
        self._page = page
        self._visible = visible
        self._enabled = enabled

    def wait_for(self, state: str = "visible", timeout: Optional[int] = None) -> None:
        if not self._visible:
            raise TimeoutError("button never became visible")

    def is_enabled(self) -> bool:
        return self._enabled

    def click(self) -> None:
        self._page.record_click()


class _FakeSimpleLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakeLoginPage:
    """Simulates the login form across N clicks.

    `login_screen_visible_after`: index i = whether the login screen is
    still visible after the (i+1)-th click (index 0 = after click 1,
    etc). Before any click, the login screen is always visible.
    """

    def __init__(
        self,
        login_screen_visible_after: List[bool],
        autofill_ready: bool = True,
        button_visible: bool = True,
        button_enabled: bool = True,
        initially_authenticated: bool = False,
        url: str = "https://vbdh.tayninh.gov.vn/dang-nhap",
    ) -> None:
        self._login_screen_visible_after = login_screen_visible_after
        self._autofill_ready = autofill_ready
        self._button_visible = button_visible
        self._button_enabled = button_enabled
        self._initially_authenticated = initially_authenticated
        self.url = url
        self.clicks = 0

    def record_click(self) -> None:
        self.clicks += 1

    def _login_screen_currently_visible(self) -> bool:
        if self.clicks == 0:
            return not self._initially_authenticated
        index = self.clicks - 1
        if index < len(self._login_screen_visible_after):
            return self._login_screen_visible_after[index]
        return True

    def locator(self, selector: str):
        if selector == 'input[name="username"]':
            return _FakeSimpleLocator(count=1 if self._login_screen_currently_visible() else 0)
        if selector == ".ui.submit.button":
            return _FakeButton(self, self._button_visible, self._button_enabled)
        return _FakeSimpleLocator(count=0)

    def get_by_text(self, _text: str) -> _FakeSimpleLocator:
        return _FakeSimpleLocator(count=0)  # menu never present; rely on login-screen-gone signal

    def wait_for_function(self, _script: str, timeout: Optional[int] = None) -> None:
        if not self._autofill_ready:
            raise TimeoutError("autofill never happened")


class _TestableBrowserSession(BrowserSession):
    """BrowserSession with get_page() overridden — no real Playwright involved."""

    def __init__(self, page: _FakeLoginPage) -> None:  # noqa: super().__init__ deliberately skipped
        self._fake_page = page

    def get_page(self):  # type: ignore[override]
        return self._fake_page


class AutomaticLoginTests(unittest.TestCase):
    """_wait_for_authentication_confirmed's real 15s timeout / 0.5s poll
    are patched down here — same production code, fast tests."""

    def setUp(self) -> None:
        patcher_timeout = patch.object(login_module, "_AUTH_CONFIRM_TIMEOUT_SECONDS", 0.3)
        patcher_poll = patch.object(login_module, "_AUTH_POLL_INTERVAL_SECONDS", 0.05)
        patcher_timeout.start()
        patcher_poll.start()
        self.addCleanup(patcher_timeout.stop)
        self.addCleanup(patcher_poll.stop)

    def test_autofill_never_happening_leaves_login_to_the_user(self) -> None:
        page = _FakeLoginPage(login_screen_visible_after=[], autofill_ready=False)
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 0)

    def test_button_never_visible_leaves_login_to_the_user(self) -> None:
        page = _FakeLoginPage(login_screen_visible_after=[], button_visible=False)
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 0)

    def test_button_never_enabled_leaves_login_to_the_user(self) -> None:
        page = _FakeLoginPage(login_screen_visible_after=[], button_enabled=False)
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 0)

    def test_successful_login_on_first_click(self) -> None:
        page = _FakeLoginPage(login_screen_visible_after=[False])  # gone after 1 click
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 1)
        self.assertFalse(session._is_login_screen_visible())

    def test_reload_back_to_login_allows_exactly_one_more_click(self) -> None:
        # Still on login after click 1, gone after click 2.
        page = _FakeLoginPage(login_screen_visible_after=[True, False])
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 2)
        self.assertFalse(session._is_login_screen_visible())

    def test_never_clicks_more_than_the_maximum_even_if_still_on_login(self) -> None:
        # Still on login after every click, however many we tried.
        page = _FakeLoginPage(login_screen_visible_after=[True, True, True, True])
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, _MAX_AUTOMATIC_LOGIN_CLICKS)
        self.assertTrue(session._is_login_screen_visible())

    def test_already_authenticated_never_clicks_at_all(self) -> None:
        page = _FakeLoginPage(login_screen_visible_after=[], initially_authenticated=True)
        session = _TestableBrowserSession(page)

        session._attempt_automatic_login(page)

        self.assertEqual(page.clicks, 0)


if __name__ == "__main__":
    unittest.main()
