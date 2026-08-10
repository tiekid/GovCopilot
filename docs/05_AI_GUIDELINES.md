# GovCopilot — AI Guidelines

This document is the full reference for GovCopilot's AI architecture.
`CLAUDE.md`'s AI Rules section is the summary; this is the detail.

## AI architecture

```
MeetingParserAgent
        ↓
AIInvitationExtractor       (ai/invitation_extractor.py)
        ↓ normalize_document_identifiers()   (ai/text_normalizer.py)
        ↓ provider.generate(prompt, text)
AIProvider (Protocol)       (providers/ai_provider.py)
        ↓
ProviderFactory.create_provider()   (providers/provider_factory.py)
        ├── OllamaProvider   (providers/ollama_provider.py)
        ├── GeminiProvider   (providers/gemini_provider.py)
        ├── OpenAIProvider   (providers/openai_provider.py) — stub
        ├── ClaudeProvider   (providers/claude_provider.py) — stub
        └── FallbackProvider (providers/fallback_provider.py) — wraps
            Gemini + Ollama for AI_PROVIDER=auto
```

Everything above `AIProvider` is provider-independent.
`AIInvitationExtractor` and `MeetingParserAgent` never import a
concrete provider class, never branch on provider name, and never know
which one is active. Only `ProviderFactory` does — and it imports each
provider class lazily, inside its own branch, so selecting `ollama`
never requires the Gemini SDK (or vice versa) to even be installed.

## ProviderFactory

`providers/provider_factory.py::create_provider(provider_name=None)`

- Defaults to `config.AI_PROVIDER`, read **at call time** (not import
  time), so a runtime config change (Settings dialog, self-healing
  model discovery) takes effect on the next call without an app
  restart.
- Supported names: `ollama`, `gemini`, `openai`, `claude`, `auto`
  (case-insensitive; empty string behaves like omitted — falls back to
  `config.AI_PROVIDER`).
- Unknown names raise `UnknownProviderError` — never silently fall
  back to a default.

## Gemini

`providers/gemini_provider.py::GeminiProvider`

- SDK: `google-genai` (the current, actively-maintained official
  package). The older `google-generativeai` package is deprecated by
  Google — do not reintroduce it. See `docs/10_ADR.md` ADR-003.
- Missing `GEMINI_API_KEY` raises `ProviderConfigurationError` at
  **construction time**, before any SDK call — never a raw SDK
  exception for a missing key.
- **No hardcoded model name.** `config.GEMINI_MODEL` defaults to `""`.
  If empty at `generate()` time, the first model supporting
  `generateContent` is discovered via `list_text_generation_models()`
  and persisted via `config_store.set_config_value`. See ADR-004 and
  `docs/09_LESSONS_LEARNED.md`.
- **404 self-heal.** If the configured model 404s (`code == 404` or
  `status == "NOT_FOUND"`), `generate()` re-discovers a replacement,
  **excluding the model that just failed** — Gemini's `models.list()`
  can still list a model that 404s for a specific account (e.g. "no
  longer available to new users"), so excluding it is required, not
  optional — and retries once.
- Every other failure (quota, timeout, network, malformed response) is
  wrapped as `GeminiProviderError`. The `except Exception` around the
  SDK call is deliberately broad: transport-level failures (DNS,
  connection refused, timeout) don't always surface as
  `google.genai.errors.APIError`.
- Model selection is first-in-`models.list()`-order, not quota- or
  cost-aware. A model earlier in the list can fail for reasons other
  than 404 (e.g. a pro-tier model with zero free-tier quota) — this is
  a known limitation, not a bug.

## Ollama

`providers/ollama_provider.py::OllamaProvider`

- HTTP API only (`POST {OLLAMA_URL}/api/chat`) — **never** the
  `ollama` CLI (`ollama run`, `ollama chat`).
- Default provider (`config.AI_PROVIDER` default is `"ollama"`) —
  local-first, no key required. See ADR-002.
- `temperature=0` — extraction is a determinism task, not creative
  generation. Also `num_ctx`, `keep_alive`, all from `config.py`.
- Request options are sent via Ollama's `options` field, never as a
  provider-level "guess it wants JSON" flag — the provider doesn't
  know or care that the caller wants JSON (see Prompt rules below).
- Failures wrap as `OllamaProviderError`.

## OpenAI / Claude

`providers/openai_provider.py`, `providers/claude_provider.py`

- Stubs. `generate()` raises `NotImplementedError` — explicit failure,
  never a silent no-op.
- Config (`OPENAI_API_KEY`/`OPENAI_MODEL`, `CLAUDE_API_KEY`/
  `CLAUDE_MODEL`) is already wired, so implementing either is a
  contained change to one file plus `ProviderFactory`'s lazy-import
  registry — no other file needs to change.

## Prompt rules

- **One prompt, one file:** `prompts/invitation_extraction.md`. Every
  provider is handed the exact same prompt text — no per-provider
  prompt variants.
- **Never hardcode a prompt in code.** `AIInvitationExtractor` loads
  it from disk once, at construction.
- The prompt asks for **document numbers only** — no title, no
  agency — matching what `VBSearchAgent` actually searches by. Text is
  already normalized (wrapped identifiers merged) before it reaches
  the model — the model does semantic extraction, never OCR/formatting
  cleanup.

## JSON parsing ownership

- **Providers return raw text. Full stop.** No JSON parsing, no schema
  validation, no `MeetingDocument` construction, no normalization,
  inside any provider. See `docs/10_ADR.md` ADR-006.
- `AIInvitationExtractor` owns all of it: `_extract_json_object` uses a
  brace-depth scanner (string/escape-aware) to find exactly one
  top-level JSON object in the raw response — tolerating incidental
  surrounding text but raising `AIInvitationExtractionError` on zero or
  multiple objects, never guessing which one is "the" answer.
- Document numbers are normalized (whitespace stripped) and
  deduplicated (first occurrence wins, order preserved) in the same
  place, for the same reason: one owner, one set of rules.

## Logging

- Every `extract_documents()` call writes `logs/ai/<timestamp>/`:
  `invitation.txt`, `prompt.md`, `response.json`, `documents.json`,
  and `metadata.json` (`provider`, `model`, `latency_ms`).
- Debug logging is best-effort: a failure to write must never fail or
  block the actual extraction — wrapped in its own try/except, logged
  as a warning.
- No credentials (API keys, auth headers) are ever written to a log
  file.

## Fallback strategy

`providers/fallback_provider.py::FallbackProvider`, selected via
`AI_PROVIDER=auto`.

- Tries `primary.generate()`; on one of `primary_error_types`, falls
  back to `secondary.generate()`. Any other exception propagates
  unfiltered — a bug in the primary is never mistaken for "provider
  unavailable" and silently masked.
- `ProviderFactory._create_auto_provider()`: if Gemini can't even be
  constructed (`ProviderConfigurationError` — no key), returns plain
  `OllamaProvider()` directly — never wraps a provider that couldn't be
  built. Once Gemini is configured, wraps it with Ollama as fallback,
  `primary_error_types=(GeminiProviderError,)`.
- `AI_PROVIDER` default is `"ollama"`, not `"auto"` or `"gemini"` —
  Gemini is an opt-in acceleration, never a silent default. See
  ADR-002.

## Model discovery

`providers/gemini_provider.py::list_text_generation_models`,
`select_first_text_generation_model`

- Lists real models via `client.models.list()`, filters for
  `"generateContent"` in `supported_actions`, strips the `models/`
  prefix.
- `select_first_text_generation_model(api_key, exclude=None)` —
  `exclude` is not decorative: real testing showed a 404'd model can
  still be listed, so a naive re-select without exclusion picks the
  same broken model again. Always exclude the model that just failed
  when re-discovering.
- Triggered by: `generate()` when `GEMINI_MODEL` is empty; the 404
  self-heal path; `MainWindow`'s startup check (key present, no model
  yet); the Settings dialog's "Kiểm tra kết nối" button.
- Selection is first-in-list-order, not quota-aware or cost-aware — see
  `docs/09_LESSONS_LEARNED.md`.

## Error handling

| Exception | Raised by | Meaning | UI treatment |
|---|---|---|---|
| `ProviderConfigurationError` | Any provider `__init__` | Not configured (e.g. missing key) | `ui/messages.py::GEMINI_NOT_CONFIGURED_MESSAGE` |
| `GeminiProviderError` | `GeminiProvider.generate()` | Request failed after any retry | `ui/messages.py::GEMINI_UNAVAILABLE_MESSAGE` |
| `OllamaProviderError` | `OllamaProvider.generate()` | HTTP/connection/response-shape failure | generic failure message |
| `AIInvitationExtractionError` | `AIInvitationExtractor` | Response isn't valid/parseable JSON | generic failure message |
| `UnknownProviderError` | `ProviderFactory.create_provider()` | `AI_PROVIDER` names an unrecognized provider | not user-facing (config error) |

A raw SDK/API exception must never reach the UI. Every provider wraps
its own failure modes in its own typed exception before it can
propagate past `generate()`.
