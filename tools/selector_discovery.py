"""Reusable developer tool: Alt+Click element/selector inspector.

Not part of the application and not tied to any specific site. Attach
to the current authenticated BrowserSession page; hold Alt and click
any element to record it — normal clicks are unaffected. Everything is
captured in injected JavaScript (localStorage, so it survives page
navigations); the collected data is pulled into Python and written to
discovery/selector.json only once, when the developer stops the tool.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from browser import BrowserSession

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path("discovery")
_OUTPUT_PATH = _OUTPUT_DIR / "selector.json"

_INSPECTOR_SCRIPT = r"""
(() => {
    const STORAGE_KEY = 'govcopilot_selector_captures';

    function loadCaptures() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function saveCaptures(captures) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(captures));
        } catch (e) {
            // Storage unavailable or full — capture is still logged to console.
        }
    }

    function getXPath(el) {
        if (el.id) {
            return `//*[@id="${el.id}"]`;
        }
        const parts = [];
        while (el && el.nodeType === Node.ELEMENT_NODE) {
            let index = 1;
            let sibling = el.previousElementSibling;
            while (sibling) {
                if (sibling.tagName === el.tagName) {
                    index += 1;
                }
                sibling = sibling.previousElementSibling;
            }
            parts.unshift(`${el.tagName.toLowerCase()}[${index}]`);
            el = el.parentElement;
        }
        return '/' + parts.join('/');
    }

    function getCssPath(el) {
        if (el.id) {
            return `#${el.id}`;
        }
        const parts = [];
        while (el && el.nodeType === Node.ELEMENT_NODE && el.tagName.toLowerCase() !== 'html') {
            let selector = el.tagName.toLowerCase();
            if (el.className && typeof el.className === 'string') {
                const classes = el.className.trim().split(/\s+/).filter(Boolean);
                if (classes.length) {
                    selector += '.' + classes.join('.');
                }
            }
            let index = 1;
            let sibling = el.previousElementSibling;
            while (sibling) {
                if (sibling.tagName === el.tagName) {
                    index += 1;
                }
                sibling = sibling.previousElementSibling;
            }
            selector += `:nth-of-type(${index})`;
            parts.unshift(selector);
            el = el.parentElement;
        }
        return parts.join(' > ');
    }

    function getDataAttributes(el) {
        const data = {};
        for (const attr of Array.from(el.attributes)) {
            if (attr.name.startsWith('data-')) {
                data[attr.name] = attr.value;
            }
        }
        return data;
    }

    function getCandidateSelectors(el, dataAttrs) {
        const nameAttr = el.getAttribute('name');
        const tag = el.tagName.toLowerCase();

        return {
            id: el.id ? `#${el.id}` : null,
            name: nameAttr ? `${tag}[name="${nameAttr}"]` : null,
            data: Object.keys(dataAttrs).map((key) => `[${key}="${dataAttrs[key]}"]`),
            css: getCssPath(el),
            xpath: getXPath(el),
        };
    }

    if (window.__govcopilotSelectorInspectorInstalled__) {
        return;
    }
    window.__govcopilotSelectorInspectorInstalled__ = true;

    document.addEventListener('click', (event) => {
        if (!event.altKey) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        const el = event.target;
        const dataAttrs = getDataAttributes(el);

        const info = {
            tag: el.tagName ? el.tagName.toLowerCase() : '',
            id: el.id || '',
            class_name: (el.className && typeof el.className === 'string') ? el.className : '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            href: el.getAttribute('href') || '',
            value: (typeof el.value !== 'undefined') ? String(el.value) : '',
            placeholder: el.getAttribute('placeholder') || '',
            aria_label: el.getAttribute('aria-label') || '',
            data_attributes: dataAttrs,
            text: (el.textContent || '').trim().slice(0, 200),
            outer_html: el.outerHTML ? el.outerHTML.slice(0, 2000) : '',
            candidate_selectors: getCandidateSelectors(el, dataAttrs),
            page_url: window.location.href,
        };

        const captures = loadCaptures();
        captures.push(info);
        saveCaptures(captures);

        console.log('[selector-discovery] captured', info.tag, info.candidate_selectors);
    }, true);
})();
"""

_READ_CAPTURES_SCRIPT = r"""
() => {
    try {
        const raw = localStorage.getItem('govcopilot_selector_captures');
        return raw ? JSON.parse(raw) : [];
    } catch (e) {
        return [];
    }
}
"""


class SelectorDiscoveryTool:
    """Alt+Click element/selector inspector attached to a BrowserSession page."""

    def __init__(self, browser_session: BrowserSession) -> None:
        self._browser_session = browser_session

    def run(self) -> None:
        """Attach the inspector and block until the developer stops it."""

        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        page = self._browser_session.open()

        page.add_init_script(_INSPECTOR_SCRIPT)
        page.evaluate(_INSPECTOR_SCRIPT)

        print("=" * 50)
        print("Selector discovery active.")
        print("Hold Alt and click any element to inspect it.")
        print("Normal clicks continue to behave normally.")
        print("Captures survive page navigation within the same site.")
        print(f"Press Enter here to stop and save results to {_OUTPUT_PATH}")
        print("=" * 50)

        input()

        captures = self._collect(page.evaluate(_READ_CAPTURES_SCRIPT))

        self._save(captures)

        logger.info("Selector discovery stopped: %d element(s) captured", len(captures))

    @staticmethod
    def _collect(raw_captures: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_captures, list):
            logger.warning("Unexpected capture payload from page; saving empty result")
            return []

        return raw_captures

    @staticmethod
    def _save(captures: List[Dict[str, Any]]) -> None:
        _OUTPUT_PATH.write_text(
            json.dumps(captures, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def run_selector_discovery() -> None:
    session = BrowserSession()

    try:
        tool = SelectorDiscoveryTool(session)
        tool.run()
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_selector_discovery()
