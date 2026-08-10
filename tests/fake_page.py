"""Fake Playwright Page/Locator/BrowserContext for FakePage-tier tests.

See docs/TESTING.md tier 2 (FakePage tests): verifies agent control
flow and Playwright call sequence without a real browser. These fakes
implement only the surface DownloadAgent (agents/download.py) actually
calls — not a general Playwright stub.
"""

from types import SimpleNamespace
from typing import Callable, Dict, List, Optional


class FakeLocator:
    """Fake Playwright Locator supporting the calls DownloadAgent makes."""

    def __init__(
        self,
        count: int = 0,
        visible: bool = True,
        enabled: bool = True,
        sub_locators: Optional[Dict[str, "FakeLocator"]] = None,
        text_matches: Optional[set] = None,
        click_error: Optional[Exception] = None,
        on_click: Optional[Callable[[], None]] = None,
        wait_for_error: Optional[Exception] = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._enabled = enabled
        self._sub_locators = sub_locators or {}
        self._text_matches = text_matches or set()
        self._click_error = click_error
        self._on_click = on_click
        self._wait_for_error = wait_for_error
        self.clicked = False

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return self._count

    def is_visible(self) -> bool:
        return self._visible

    def is_enabled(self) -> bool:
        return self._enabled

    def locator(self, selector: str) -> "FakeLocator":
        return self._sub_locators.get(selector, FakeLocator())

    def get_by_text(self, text: str) -> "FakeLocator":
        return FakeLocator(count=1) if text in self._text_matches else FakeLocator(count=0)

    def wait_for(self, state: Optional[str] = None, timeout: Optional[int] = None) -> None:
        if self._wait_for_error is not None:
            raise self._wait_for_error

    def click(self, timeout: Optional[int] = None) -> None:
        """Mirror real Playwright auto-waiting: a locator matching nothing times out."""

        if self._count == 0 and self._click_error is None:
            raise TimeoutError("Locator matched no elements")

        if self._on_click is not None:
            self._on_click()

        if self._click_error is not None:
            raise self._click_error

        self.clicked = True


class FakeEventEmitter:
    """Minimal stand-in for Playwright's Page/BrowserContext event methods."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List] = {}

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    def emit(self, event: str, *args) -> None:
        for handler in list(self._handlers.get(event, [])):
            handler(*args)


class FakeDownload:
    """Fake Playwright Download."""

    def __init__(self, suggested_filename: str = "attachment.pdf") -> None:
        self.suggested_filename = suggested_filename
        self.saved_to = None

    def save_as(self, path) -> None:
        self.saved_to = path


class FakeExpectDownloadContext:
    """Fake for `with page.expect_download() as info:` — the crux of failure mode 3.

    If `raise_on_exit` is set, __exit__ raises it (simulating a click
    that never produces a Playwright download event); otherwise the
    context yields `info.value` = the configured FakeDownload.
    """

    def __init__(self, download: Optional[FakeDownload], raise_on_exit: Optional[Exception]) -> None:
        self._info = SimpleNamespace(value=download)
        self._raise_on_exit = raise_on_exit

    def __enter__(self) -> SimpleNamespace:
        return self._info

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False
        if self._raise_on_exit is not None:
            raise self._raise_on_exit
        return False


class FakeKeyboard:
    """Fake Playwright Keyboard — records presses (e.g. DownloadAgent's dialog-close Escape)."""

    def __init__(self) -> None:
        self.pressed: List[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class FakePage(FakeEventEmitter):
    """Fake Playwright Page supporting the calls DownloadAgent makes."""

    def __init__(
        self,
        locators: Dict[str, FakeLocator],
        download: Optional[FakeDownload] = None,
        raise_on_download_wait: Optional[Exception] = None,
        raise_on_wait_for_load_state: Optional[Exception] = None,
        url: str = "https://vbdh.tayninh.gov.vn/detail",
        frames: Optional[List] = None,
    ) -> None:
        super().__init__()
        self._locators = locators
        self._download = download
        self._raise_on_download_wait = raise_on_download_wait
        self._raise_on_wait_for_load_state = raise_on_wait_for_load_state
        self.url = url
        self.main_frame = object()
        self.context = FakeEventEmitter()
        self.keyboard = FakeKeyboard()
        # Defaults to just the main frame (no iframes) — pass extra
        # entries to simulate an iframe-embedded viewer (Bug 3).
        self.frames = frames if frames is not None else [self.main_frame]
        # Records whatever timeout the caller passed to expect_download(),
        # so tests can assert the adaptive timeout was actually computed
        # and threaded through (not just that *some* timeout was used).
        self.last_expect_download_timeout_ms: Optional[int] = None

    def locator(self, selector: str) -> FakeLocator:
        return self._locators.get(selector, FakeLocator())

    def wait_for_load_state(self, state: str, timeout: Optional[int] = None) -> None:
        if self._raise_on_wait_for_load_state is not None:
            raise self._raise_on_wait_for_load_state

    def expect_download(self, timeout: Optional[int] = None) -> FakeExpectDownloadContext:
        self.last_expect_download_timeout_ms = timeout
        return FakeExpectDownloadContext(self._download, self._raise_on_download_wait)


class FakeResponse:
    """Fake Playwright Response — for testing the response-content-type capture (Bug 3)."""

    def __init__(self, url: str, status: int = 200, content_type: str = "application/pdf") -> None:
        self.url = url
        self.status = status
        self.headers = {"content-type": content_type}


class FakeBrowserSession:
    """Fake BrowserSession that hands back a pre-built FakePage."""

    def __init__(self, page: FakePage) -> None:
        self._page = page

    def get_page(self) -> FakePage:
        return self._page
