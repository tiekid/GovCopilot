# GovCopilot — Architecture Decision Records

Each record: Status, Context, Decision, Consequences. Numbered
sequentially in the order decided.

## ADR-001: Multi-provider AI architecture

**Status:** Accepted

**Context:** The original `AIInvitationExtractor` imported the OpenAI
SDK directly and required `OPENAI_API_KEY`. The project needed to run
fully offline (Ollama) and support additional providers (Gemini, and
future OpenAI/Claude) without `AIInvitationExtractor` or
`MeetingParserAgent` ever knowing which one is active.

**Decision:** Introduce an `AIProvider` Protocol
(`providers/ai_provider.py`) with a single method,
`generate(system_prompt, user_prompt) -> str`, plus `name`/`model`
properties for logging. A `ProviderFactory`
(`providers/provider_factory.py::create_provider`) is the only place
that imports a concrete provider class, selected by
`config.AI_PROVIDER`. Every provider is stateless — no prompt,
conversation, or model state cached between calls.

**Consequences:** Adding a new provider touches exactly two files (the
new provider, plus one line in `ProviderFactory`'s registry) and never
`AIInvitationExtractor` or `MeetingParserAgent`. Providers stay
trivially swappable and independently testable with fakes.

## ADR-002: Ollama as the default provider

**Status:** Accepted

**Context:** Mid-project, `AI_PROVIDER`'s default was briefly changed
to `"gemini"` while building the Gemini provider. This silently made
every fresh install depend on a paid, external API by default,
contradicting the project's local-first origin.

**Decision:** `AI_PROVIDER` defaults to `"ollama"`. Gemini (`gemini` or
`auto`) is always an explicit opt-in, never the out-of-the-box
default.

**Consequences:** A fresh checkout with no `.env` configuration works
fully offline, no API key required. Gemini's speed/quality is
available on request via one config line.

## ADR-003: Gemini via google-genai, not google-generativeai

**Status:** Accepted

**Context:** The originally-planned SDK, `google-generativeai`, turned
out to be deprecated by Google ("All support ... has ended") the
moment it was imported (a `FutureWarning` at import time), discovered
before anything shipped against it.

**Decision:** Use `google-genai` (the current, actively-maintained
official SDK) instead —
`client.models.generate_content(model=..., contents=...,
config=GenerateContentConfig(system_instruction=..., temperature=0))`.

**Consequences:** `providers/gemini_provider.py` and
`requirements.txt` depend on `google-genai` only; the deprecated
package was never added to `requirements.txt`.

## ADR-004: No hardcoded Gemini model name

**Status:** Accepted

**Context:** A hardcoded default model name (`gemini-2.5-flash`) went
stale in production almost immediately — Google restricted it for new
accounts. See `docs/09_LESSONS_LEARNED.md`.

**Decision:** `config.GEMINI_MODEL` defaults to empty. `GeminiProvider`
discovers the first model supporting `generateContent` from the live
API on first use (or via Settings > "Kiểm tra kết nối"), persists it
via `config_store.set_config_value`, and self-heals once on a
`404 NOT_FOUND`, always excluding the model that just failed when
re-discovering.

**Consequences:** No model name is ever committed to source or `.env`
by a developer's guess. The system adapts automatically as Google
retires/renames models, at the cost of one extra API call the first
time (or after a retirement) and the accepted limitation that
selection is listing-order, not quota-aware.

## ADR-005: Gemini→Ollama automatic fallback ("auto")

**Status:** Accepted

**Context:** Gemini can be faster/higher-quality but is an external
dependency with its own failure modes (quota, network, retired
models). Ollama is always available locally but slower. Neither
should be a single point of failure for the pipeline.

**Decision:** `FallbackProvider` (`providers/fallback_provider.py`)
wraps a primary and fallback provider; `AI_PROVIDER=auto` constructs
Gemini as primary and Ollama as fallback via
`ProviderFactory._create_auto_provider`. If Gemini can't even be
constructed (no key), `auto` returns plain `OllamaProvider` directly.
Only exceptions in `primary_error_types` trigger the fallback; anything
else propagates.

**Consequences:** `auto` mode is resilient to Gemini being
unconfigured, out of quota, or unreachable — verified in production
against a real 404 → 429 → Ollama-success chain. It is not the default
(ADR-002) — an explicit choice.

## ADR-006: JSON parsing owned by AIInvitationExtractor, not providers

**Status:** Accepted

**Context:** See `docs/09_LESSONS_LEARNED.md`'s "Providers never parse
JSON" — an early interface candidate would have pushed JSON parsing
into every provider implementation.

**Decision:** `AIProvider.generate()` returns raw text only.
`AIInvitationExtractor` owns prompt loading, text normalization, JSON
extraction (brace-depth scanning, tolerant of surrounding text, strict
on ambiguity), number normalization, deduplication, and
`MeetingDocument` construction — in one place, regardless of which
provider produced the text.

**Consequences:** A provider is a pure transport adapter. Domain logic
changes (e.g. the brace-depth JSON scanner) happen once, benefit every
provider, and are testable independent of any specific SDK.

## ADR-007: DownloadAgent instrumentation before behavior change

**Status:** Accepted

**Context:** Three `DownloadAgent` failure modes were reported (dialog
not ready, "Không có dữ liệu", click without a download event) without
confirmed root causes.

**Decision:** Instrument first: `DownloadDiagnostics` captures 13
signals per document to `logs/download/<document-number>.json`,
without changing any existing download control flow. The actual fix
is deferred until real examples of each failure mode are captured.

**Consequences:** `agents/download.py` currently ships instrumentation
without the corresponding behavior fix — an intentional, temporary
state, tracked until real evidence arrives. Establishes the
evidence-before-implementation pattern formalized in
`docs/02_WORKFLOW.md`.

## ADR-008: Network-response completion signal for VBĐH search

**Status:** Accepted

**Context:** See `docs/09_LESSONS_LEARNED.md`'s "Zero-result search
behavior" — a DOM-based completion signal was confirmed unreliable for
zero-result searches specifically.

**Decision:** `VBSearchAgent._submit_search` waits on the real
`GetVanBansByPage` network response via `page.expect_response(...)`,
not any DOM state, and treats a non-200 response as a search failure
distinct from a legitimate zero-result search.

**Consequences:** Search result handling is correct for both 0 and N
results without a special-cased zero-result branch. Any future VBĐH
workflow needing a completion signal should look for the underlying
API call first, per `docs/06_PLAYWRIGHT.md`.

## ADR-009: Single source-of-truth prompt file

**Status:** Accepted

**Context:** Multi-provider support raised the question of whether
each provider might need its own prompt tuning.

**Decision:** Exactly one prompt file,
`prompts/invitation_extraction.md`, loaded once by
`AIInvitationExtractor` and passed unchanged to whichever provider is
active. It requests document numbers only (no title/agency), matching
what `VBSearchAgent` actually searches by.

**Consequences:** Prompt changes benefit every provider simultaneously
and there is never a question of which provider used which prompt
version. Provider-specific quirks (e.g. not requesting a JSON mime
type from the transport layer) are handled in the provider, not by
forking the prompt.

## ADR-010: requirements.txt lists direct dependencies only

**Status:** Accepted

**Context:** See `docs/09_LESSONS_LEARNED.md` — a `pip freeze` dump
included dozens of unused/transitive packages.

**Decision:** `requirements.txt` is maintained by tracing actual
`import`/`from` statements across the codebase, pinning only direct
dependencies (currently 7: `python-dotenv`, `pypdf`, `python-docx`,
`playwright`, `PySide6`, `requests`, `google-genai`). Transitive
dependencies are left to `pip`'s own resolution.

**Consequences:** The file stays a true reflection of what the
codebase actually uses. Adding a new direct dependency requires an
explicit, reviewable one-line addition; nothing arrives silently via a
freeze.

## ADR-011: Google Drive support added to DownloadAgent as a second, independent path

**Status:** Accepted

**Context:** `docs/GovCopilot-v2-kien-truc.md` §3.1 locked the target
architecture: the invitation's QR code points to a shared Google Drive
folder (parent meeting folder → one ND subfolder per agenda item →
loose files, no zip); VBĐH becomes a fallback. `scripts/test_drive_api_v3.py`,
run against the real folder on 2026-08-22, confirmed an API-key-only
(no OAuth) call to Drive API v3 can list a folder's contents
(`files.list`) and download original bytes (`files.get?alt=media`)
with byte-exact size verification. A follow-up real call against the
parent folder ID confirmed every direct child is a subfolder
(`mimeType: application/vnd.google-apps.folder`) — one level of
subfolder recursion before real files, as expected. `DownloadAgent`
(`agents/download.py`) previously had zero Drive awareness — VBĐH
Playwright automation only.

**Decision:** Add `DownloadAgent.download_from_drive()` alongside the
existing `download()`, sharing no Playwright state with it (no browser
session, no dialog) and returning the same `DownloadResult`, mutating
`MeetingDocument.downloaded`/`local_path` identically — so
`NormalizationAgent` and the pipeline require no changes. All Drive
HTTP calls live in a new transport-only module, `agents/drive_client.py`
(mirrors the `providers/` split for AI: it returns raw listings/bytes
only, never makes matching or traversal decisions). Errors are typed
three ways — `DriveForbiddenError` (HTTP 403, a sharing/permission
problem), `DriveNetworkError` (no HTTP response at all), and
`DriveApiError` (any other non-2xx) — so a folder shared more
restrictively than "Anyone with the link" is diagnosed immediately,
never mistaken for a flaky connection. `download_from_drive()` lists
its given folder ID and recurses exactly one level into any subfolders
found (handling both the parent-folder and single-ND-folder calling
shapes), matches `MeetingDocument.number` against candidate file names
by leading digit sequence (the only pattern confirmed by real
evidence), and dispatches to `download_binary` or `export_native_file`
by mimeType — the native-Google-file export path (Docs/Sheets/Slides)
is implemented per the Drive API v3 reference but not yet exercised
against a real native file, and logs a distinct warning the first time
it fires in production.

**Explicitly deferred (not decided by this ADR):**
- Extracting the parent Drive folder ID from the invitation's QR code —
  no code path for this exists yet.
- Matching an ND subfolder name (e.g. "ND 13.4 - 9414") to
  `AgendaItem.index`/`MeetingDocument.agenda_item_index` — only one
  real meeting's folder names have been observed, and not all follow a
  `number` suffix (e.g. "ND 2.3 (CHUA CO TAI LIEU)", "ND 5 - DM KY HOP"
  were both observed in the same real parent folder).
- Wiring `download_from_drive()` into `pipeline/document_pipeline.py`'s
  loop (the "Drive primary / VBĐH fallback" decision from
  `GovCopilot-v2-kien-truc.md` §3.1) — needs the two gaps above
  resolved first.

**Consequences:** `DownloadAgent` now has two download sources behind
one contract, so downstream code is unaffected by which one runs. The
Drive path is real and unit-tested (`tests/test_drive_client.py`,
`tests/test_download_agent_drive.py`) but not yet reachable from the
pipeline — it must be explicitly wired in a future, separately approved
change once the deferred items above are resolved.

## ADR-012: NDContentExtractor — Gemini-backed free-text extraction, one shared parser, two callers

**Status:** Accepted

**Context:** `docs/GovCopilot-v2-kien-truc.md` §3.2 locked a two-tier AI
review architecture: Gemini extracts each ND bundle's content
faithfully (no summarizing, no analysis), then a human + Claude analyze
that extraction in a 6-section framework during a Cowork session.
`ReviewAgent` already implements the second tier (reads back an
externally-produced `NDxx.review.md`, never calls AI — unchanged). This
ADR covers only the first tier.

`docs/ARCHITECTURE.md`'s hard rule read: "Agents never read PDF/DOCX
directly. Only `parser/invitation_reader.py` touches file formats.
Every agent downstream of it operates on the `Meeting` object or plain
text already extracted from it." Read literally, this implies a single
caller (everything downstream operates on already-extracted text) —
but `NDContentExtractor` genuinely needs to read PDF/DOCX files
(documents inside an `NDxx.zip`, never seen by `InvitationReader`
before). Investigation showed `parser/invitation_reader.py` already
has `read_pdf`/`read_docx` as independently-callable standalone
functions, not private logic needing extraction — so the real
invariant this codebase needs is "one parsing *implementation*," not
"one caller."

**Decision:** `NDContentExtractor` (`ai/nd_extractor.py`) calls
`read_invitation()` directly — no restructuring of
`parser/invitation_reader.py` needed for that. The hard rule is
reworded to "No agent implements its own PDF/DOCX parsing" (see
`docs/ARCHITECTURE.md`), explicitly naming `NDContentExtractor` as a
second, legitimate caller of the same shared module.

`NDContentExtractor` reuses the exact `AIProvider` protocol and
`provider_factory.create_provider()` that `AIInvitationExtractor`
already uses (same constructor pattern: inject a provider or build one
via `create_provider()`) — zero changes to `providers/ai_provider.py`,
`providers/provider_factory.py`, or `providers/gemini_provider.py`.
Unlike `AIInvitationExtractor` (which JSON-parses the response),
`NDContentExtractor` does no response parsing at all: the provider's
raw text (stripped) *is* the output file's content, written as
`NDxx.extract.md` next to the bundle. It reads the zip's own real
`namelist()` for the file list — never `NDxx.meta.json`'s
`danh_sach_file`, which can list a file no longer actually in the zip.

**Real bug found and fixed during planning:** `read_docx()` only
iterated `doc.paragraphs`, silently dropping all table content — table
cell text lives in `doc.tables` and was completely invisible to it.
Verified against a real DOCX (`test_downloads/TMTT-QHC HOA THANH.docx`,
tải qua Drive API cùng phiên): 742 paragraphs, 27 tables containing
real data (approving/appraising agency, project lead, etc.). This
wasn't a crash and wasn't an empty string, so it couldn't be caught by
the scanned-file detection logic — an ND would be processed and
silently missing every table's content, directly contradicting §3.2's
"giữ nguyên số liệu, không rút gọn mất thông tin" for extraction
category 6 ("Bảng biểu, phụ lục quan trọng"). Fixed: `read_docx()` now
appends each table's content after the paragraph text, one `[Bảng N]`-
fenced block per table with pipe-delimited rows, so a consumer can tell
table data from prose. **Known, accepted limitation, not a bug:**
tables are appended after all paragraph text, not interleaved back
into their original position — acceptable because the goal is faithful
content extraction, not document-layout reconstruction. No existing
test exercised `read_docx()` before this fix (confirmed via repo-wide
grep) — `tests/test_invitation_reader.py` is this module's first test
file.

**Known v1 limitation, confirmed intentional (parallel to ADR-011's
`export_native_file`-untested-path disclosure):** one unreadable/empty/
unsupported file in an ND's bundle skips that **whole** ND, not just
that one file — partial extraction was rejected because it would
silently produce an incomplete `NDxx.extract.md` with no signal of what
was omitted, which is worse than a loud, fully-skipped ND that's easy
to notice and revisit.

**Explicitly deferred (not decided by this ADR):**
- The ~5/27 scanned-PDF NDs (measured in `docs/GovCopilot-v2-kien-truc.md`
  §4) — detected and skipped, not processed; multimodal handling is
  separate future work.
- Wiring `NDContentExtractor` into `pipeline/document_pipeline.py` —
  not yet done; a separate, later approval once this component is
  proven, per the same precedent as ADR-011.
- A real Gemini API call — this ADR's code+tests use a mocked provider
  exclusively; testing against the real API is a separate,
  case-by-case-approved step.

**Real evidence for future Drive-wiring work (see ADR-011's deferred
item "wiring `download_from_drive` into the pipeline"):** a real-data
scan of all 21 ND subfolders (`files.list`, metadata only, 2026-08-22)
found 96 files total — 86 PDF, 8 DOCX, 1 real `.xlsx` (ND 8 - 5226,
ngân sách Techfest, `20.8_Du_toan_Techfest_Tay_Ninh_2026...xlsx`), and
1 real `.zip` (ND 10.1 - 13015, hồ sơ hành chính, ~52.6MB). Zero
Google-native files (`application/vnd.google-apps.*`).
`NDContentExtractor`'s current pdf/docx-only scope will skip both of
these NDs entirely once Drive is wired in (logged, not crashed — falls
into the existing "unsupported file type" branch). Note: the `.zip`
found here is a real attachment file that happens to be a zip container
(an administrative dossier), NOT the Drive-folder auto-zip-on-download
problem §3.1 already eliminated — the two are unrelated. Before or
alongside wiring Drive into the pipeline, this ND's `.zip` needs its
own handling decision (likely: extract and treat its contents as more
loose files, matching Drive's own no-zip philosophy) and the `.xlsx`
needs `read_xlsx()` support (via `openpyxl`) — neither is addressed by
this ADR.

**Consequences:** `NDContentExtractor` is a strictly simpler consumer
of the same provider contract `AIInvitationExtractor` already
established — no new provider-layer code. `read_docx()`'s real bug is
fixed for every caller (`MeetingParserAgent` included), not just this
new one. The pdf/docx-only, all-or-nothing-per-ND scope is real and
tested but deliberately narrow — the deferred items above are tracked
here precisely so they aren't silently forgotten or re-investigated
from scratch later.
