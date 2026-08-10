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
