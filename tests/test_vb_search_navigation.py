"""Unit tests for agents/vb_search.py's navigation race-condition fix.

"Never call goto(login_url) once authentication has already started" —
_navigate_to_search_page must skip re-navigating to _LOGIN_URL when
already on the search page, so a multi-document batch doesn't
re-trigger a login-URL navigation (and VBĐH's own redirect-away-if-
authenticated) once per document.
"""

import unittest
from typing import List

from agents.vb_search import VBSearchAgent


class _FakeLocator:
    def __init__(self) -> None:
        self.clicked = False

    def click(self) -> None:
        self.clicked = True

    def get_by_text(self, _text: str) -> "_FakeLocator":
        return self

    def get_by_role(self, _role: str, name: str) -> "_FakeLocator":
        return self


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.goto_calls: List[str] = []

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)

    def get_by_text(self, _text: str) -> _FakeLocator:
        return _FakeLocator()

    def get_by_role(self, _role: str, name: str) -> _FakeLocator:
        return _FakeLocator()


class NavigateToSearchPageTests(unittest.TestCase):

    def setUp(self) -> None:
        self.agent = VBSearchAgent(browser_session=None)  # not used by _navigate_to_search_page

    def test_navigates_via_login_url_when_not_on_search_page(self) -> None:
        page = _FakePage(url="https://vbdh.tayninh.gov.vn/dang-nhap")

        self.agent._navigate_to_search_page(page)

        self.assertEqual(page.goto_calls, ["https://vbdh.tayninh.gov.vn/dang-nhap"])

    def test_skips_navigation_when_already_on_search_page(self) -> None:
        page = _FakePage(url="https://vbdh.tayninh.gov.vn/van-ban/tim-kiem/van-ban-den")

        self.agent._navigate_to_search_page(page)

        self.assertEqual(page.goto_calls, [])

    def test_second_document_in_a_batch_never_renavigates_to_login_url(self) -> None:
        # Simulates the real race: document 1's search lands on the
        # search page; document 2's search must not goto(_LOGIN_URL)
        # again.
        page = _FakePage(url="https://vbdh.tayninh.gov.vn/dang-nhap")

        self.agent._navigate_to_search_page(page)  # document 1
        self.assertEqual(len(page.goto_calls), 1)

        page.url = "https://vbdh.tayninh.gov.vn/van-ban/tim-kiem/van-ban-den"  # where doc 1 ended up

        self.agent._navigate_to_search_page(page)  # document 2

        self.assertEqual(len(page.goto_calls), 1)  # still just the one, from document 1


if __name__ == "__main__":
    unittest.main()
