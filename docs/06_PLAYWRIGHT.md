# GovCopilot — Playwright Guidelines

Browser automation against VBĐH (`browser/`, `agents/vb_search.py`,
`agents/download.py`) follows these rules without exception.

## Browser rules

- `browser/login.py::BrowserSession` is the only place a Playwright
  `BrowserContext`/`Page` is opened. It launches a persistent, headed
  (`headless=False`) Chromium via `launch_persistent_context`, reusing
  the on-disk profile so a manual login survives across runs.
- `BrowserSession` reports observable state
  (`SessionState.AUTHENTICATED` / `LOGIN_REQUIRED`) — it never decides
  what to do with that state. Login itself stays manual today; no
  agent auto-fills credentials into the VBĐH login form.
- Every selector in `agents/vb_search.py` and `agents/download.py` is
  either (a) verified against the real VBĐH system via Playwright
  Codegen / captured markup, or (b) a deliberately generic query
  (e.g. `#formXuLy table`, not a guessed class name) used specifically
  *because* the real selector isn't verified yet — see
  `agents/download.py`'s diagnostic instrumentation. Never a guessed
  specific selector presented as verified.
- No agent constructs a new `BrowserSession`/tab mid-task — one shared
  session flows through `VBSearchAgent` → `DownloadAgent` for a given
  document, exactly as `docs/ARCHITECTURE.md` requires.

## Completion signals

- **A completion signal must be observed, not assumed.** Before
  writing code that waits for "the page to be ready," capture what
  actually changes — a specific network response, a specific selector
  appearing, a specific event — using a real session against the real
  system (or, at minimum, log every candidate signal and let the
  evidence pick one).
- `agents/download.py::DownloadDiagnostics` is the reference pattern:
  every processed document logs `dialog_opened`, `dialog_rendered`,
  `attachment_table_detected`, `attachment_row_count`,
  `no_data_present`, `download_control_present/visible/enabled`,
  `download_click_performed`, `download_event_received`,
  `navigation_occurred`, `new_tab_opened`, and the URL before/after —
  to `logs/download/<document-number>.json`. This is what "find the
  real signal" looks like in practice: instrument comprehensively,
  observe real cases, then implement based on what was actually seen —
  never before that.

## expect_response

`agents/vb_search.py::VBSearchAgent._submit_search` — the reference
pattern:

```python
with page.expect_response(
    lambda response: _SEARCH_RESPONSE_URL_SUBSTRING in response.url,
    timeout=_SEARCH_RESPONSE_TIMEOUT_MS,
) as response_info:
    page.locator(_SEARCH_FORM_SELECTOR).get_by_text(_SEARCH_SUBMIT_TEXT).click()

response = response_info.value
if response.status != 200:
    raise RuntimeError(...)
```

- Wait for the **actual network request/response** the action
  triggers, not a DOM side effect of it. Verified against the real
  system: DOM rendering was confirmed to differ for a 0-result search
  vs. an N-result search in ways that made a DOM-based wait unreliable,
  while the response itself resolves correctly either way — see
  `docs/09_LESSONS_LEARNED.md`.
- A non-200 response is a search *failure*, not "not found." Don't
  conflate transport/server errors with a legitimate empty result.

## expect_download

`agents/download.py::DownloadAgent.download` — the click and the
download-event wait are two different things that can fail
independently:

```python
with page.expect_download() as download_info:
    page.locator(_DOWNLOAD_BUTTON_SELECTOR).click()
download = download_info.value
```

- `page.expect_download()` can time out even though the click
  succeeded — VBĐH may open a new tab, serve an inline viewer, or
  navigate instead of firing a Playwright download event. Never assume
  a click always becomes a download; instrument to see which of these
  actually happens for a given document (`DownloadDiagnostics` captures
  `new_tab_opened`, `navigation_occurred`, and the URL before/after
  specifically for this reason).
- Attach `new_tab`/`navigation` listeners **before** the click, and
  remove them in a `finally` — a listener left attached across a batch
  of documents is a leak.

## Angular rendering

- VBĐH's UI is an Angular SPA. `page.wait_for_load_state("networkidle")`
  measures **network** quiescence — it does not guarantee Angular has
  finished a digest cycle / DOM update after data arrives.
  `networkidle` becoming true is a candidate signal worth logging, not
  a proven one — see `docs/09_LESSONS_LEARNED.md`
  ("networkidle != Angular render").
- When a real completion signal for a specific dialog/component isn't
  yet verified, log multiple candidates side by side (network state, a
  specific selector's presence, row counts) against real cases before
  picking one to rely on in production code.

## VBĐH investigation workflow

1. Instrument (diagnostics/logging), never guess.
2. Reproduce with real, specific documents/cases — never synthetic
   stand-ins presented as if they were real VBĐH behavior.
3. Capture one example per distinct failure mode before proposing a
   fix.
4. Implement the minimum fix the evidence supports; do not bundle in
   unrelated behavior changes.
5. See `docs/02_WORKFLOW.md`'s Bug investigation workflow and
   Investigation budget for the general form of this.

## Never use wait_for_timeout()

- `page.wait_for_timeout(ms)` and bare `time.sleep(ms)` are banned in
  application code. A fixed sleep is either too short (flaky) or too
  long (slow, and still not guaranteed correct) — it papers over not
  knowing the real completion signal instead of finding it.
- Legitimate Playwright waits are always tied to a real, observable
  condition: `expect_response`, `expect_download`, `wait_for_selector`,
  `wait_for_load_state` (understood per the Angular caveat above) —
  never an arbitrary duration.
- If a real completion signal genuinely isn't known yet, that's an
  investigation task (instrument and observe), not a sleep.
