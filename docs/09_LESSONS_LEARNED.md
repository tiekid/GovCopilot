# GovCopilot — Lessons Learned

Concrete lessons from building GovCopilot, kept here so they don't get
relearned. Each entry: what happened, what we learned, the resulting
rule.

## networkidle != Angular render

VBĐH's detail dialog is rendered by Angular after data arrives.
`page.wait_for_load_state("networkidle")` only tells you the network
went quiet — it does not tell you Angular finished updating the DOM.
Treating `networkidle` as "the dialog is ready" is a plausible-looking
but unverified assumption.

**Rule:** `networkidle` is one candidate completion signal to log
alongside others (selector presence, row counts), never assumed
correct on its own. See `docs/06_PLAYWRIGHT.md`.

## Zero-result search behavior

Early VBĐH search work assumed a DOM signal could tell 0 results from
N results apart. Verified against the real system: **the DOM was
confirmed to render nothing at all for a zero-result search** — no
error, no "not found" element, nothing to key a wait off of. The
actual search response (`GetVanBansByPage`) resolves correctly either
way, and is what `VBSearchAgent` waits on instead.

**Rule:** prefer the real network response over any DOM signal when
the two might diverge — verify which one is actually reliable before
depending on it. See `docs/06_PLAYWRIGHT.md`'s `expect_response`
section.

## Providers never parse JSON

Early in the multi-provider design, one candidate `AIProvider`
interface shape returned typed `MeetingDocument` objects directly
(`extract_documents(text) -> list[MeetingDocument]`), which would have
required every provider (Ollama, Gemini, future OpenAI/Claude) to
reimplement JSON parsing, validation, and deduplication independently.

**Rule:** `AIProvider.generate()` returns raw text only. Every other
provider-agnostic concern lives in exactly one place,
`AIInvitationExtractor`. See `docs/10_ADR.md` ADR-006.

## Do not regenerate requirements.txt using pip freeze

`pip freeze` was used once to regenerate `requirements.txt` after
adding the Gemini SDK. It captured the entire transitive dependency
graph (~57 packages) plus leftover packages the codebase never
actually imports (`openai`, `numpy`, `pandas`, `lxml`,
`beautifulsoup4`, ...). Tracing every real `import`/`from` in the
codebase found only 7 direct dependencies; `pip install -r
requirements.txt` with just those 7 resolves the full transitive chain
correctly on its own.

**Rule:** `requirements.txt` lists direct dependencies only, verified
against actual imports — never a raw `pip freeze` dump. Let pip
resolve transitives from each package's own metadata. See
`docs/10_ADR.md` ADR-010.

## Model discovery instead of hardcoded model names

`GEMINI_MODEL` was originally a hardcoded default
(`"gemini-2.5-flash"`). Real testing against the live API showed this
exact model returns `404 NOT_FOUND` ("no longer available to new
users") for this account — even though it's still listed by
`models.list()`. The first fix (re-discover and retry) had a second
bug: re-discovery without excluding the failed model could pick the
exact same broken model again, since the API still lists it.

**Rule:** never hardcode a model name. Discover it from
`models.list()`, and when re-discovering after a failure, always
exclude the model that just failed — "still listed" does not mean
"usable by this account." See `docs/10_ADR.md` ADR-004 and
`docs/05_AI_GUIDELINES.md`'s Model discovery section.

## Evidence before implementation

Twice in this project, a fix was deferred specifically to gather
evidence first rather than guess: `DownloadAgent`'s three reported
failure modes (dialog not ready, "Không có dữ liệu", click without a
download event) were investigated via comprehensive diagnostic logging
(`DownloadDiagnostics`) *before* any download-logic change was made.
Separately, a reported "incorrect fallback to gemini-2.5-pro" turned
out not to be a bug at all — printing the exact strings from
`models.list()` and the exact string passed to `generate_content()`
proved they matched, and that `gemini-2.5-pro` was genuinely the next
model in API-listed order, not a hardcoded guess. The real issue found
by that same investigation was different and real: `gemini-2.5-flash`
genuinely 404s for this account, and a naive retry can re-select the
same failed model unless it is explicitly excluded.

**Rule:** when behavior is uncertain or disputed, capture the real
data first (logs, diagnostics, exact request/response comparison).
Implementing — or reverting — before that evidence exists risks fixing
the wrong thing, or "fixing" something that was never actually broken.
See `docs/02_WORKFLOW.md`'s Bug investigation workflow.
