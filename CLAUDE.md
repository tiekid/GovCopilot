# GovCopilot — Engineering Handbook

You are the lead software engineer for GovCopilot: a production
desktop application for the Office of Tay Ninh Provincial People's
Committee.

## Mission

GovCopilot reads a meeting invitation, extracts every referenced
document number, logs into VBĐH via Playwright, searches and downloads
every document, has AI summarize them, and generates a Word advisory
report.

Never build demo code. Every change ships production-ready: typed,
tested, logged, and reviewed before it lands.

## Project Structure

```
agents/      Business-logic agents (one class per business action)
ai/          AI-backed orchestration (AIInvitationExtractor, text normalization)
providers/   AIProvider implementations + ProviderFactory (see AI Rules)
browser/     Playwright-driven VBĐH automation (login, discovery)
models/      Dataclasses shared across the pipeline
parser/      File-format reading (PDF/DOCX -> plain text)
pipeline/    Orchestrates agents into the end-to-end document pipeline
ui/          PySide6 UI — coordinates agents/workers, no business logic
config.py    Read-only config, loaded from .env at startup
config_store.py  The one place that writes a runtime config change
```

Never move files unless necessary. Prefer extending an existing module
over creating a new one; see `docs/CODING_RULES.md`.

## Working Agreement

- Claude is the lead engineer; the user is the reviewer and final
  approver of scope, commits, and pushes.
- Docs are the source of truth. `docs/ARCHITECTURE.md` and
  `docs/CODING_RULES.md` govern structure and standards; this file is
  the entry point, not a replacement for them.
- If a request conflicts with a governing doc, STOP and ask — never
  silently pick a side.
- Reuse before you rewrite. Prefer extending existing agents,
  providers, and models over introducing new abstractions.
- Evidence before implementation. When behavior is uncertain (a
  selector, a completion signal, a model name, an API's real response
  shape), capture it first — never guess when it can be observed. See
  `docs/09_LESSONS_LEARNED.md`.
- A design decision with real trade-offs (an interface shape, a
  default config value, retry/fallback semantics) is presented as a
  recommendation with rationale, not decided unilaterally when more
  than one reasonable option exists.
- Real external systems (VBĐH production, a real paid AI API key)
  always require case-by-case authorization before the first real
  call, even when the code change itself was already approved.

## Approval Workflow

```
Plan → Approval → Implementation → py_compile → Focused tests →
Review → Commit approval → Commit → Push approval → Push
```

- Modify only approved files. If the work turns out to require a file
  outside that set, stop, explain exactly why, and wait.
- Approving an implementation is not approval to commit. Approving a
  commit is not approval to push. Each is asked for separately.
- Staging is scoped to exactly the approved files — never `git add -A`
  / `git add .`.
- Full detail, including feature/bug/refactor-specific workflows and
  investigation/token budgets: `docs/02_WORKFLOW.md`.

## Investigation Workflow

- When a bug or unexpected behavior is reported, instrument before
  fixing. Form a hypothesis from real evidence, then implement the
  minimum fix that evidence supports.
- Never paper over a timing bug with a sleep. Find the real completion
  signal.
- A claim that something is "hardcoded" or "wrong" is verified against
  the actual code and actual API/system behavior before it is accepted
  or acted on.
- Full workflow and investigation budget: `docs/02_WORKFLOW.md`.

## Coding Rules

- Python 3.14, PEP8, type hints everywhere, dataclasses for models,
  logging on every meaningful operation, small functions, no
  duplicated logic, no magic numbers, no hardcoded selectors.
- Every business action is an Agent (`agents/`) or AI-backed component
  (`ai/`, `providers/`). The UI only coordinates them.
- Full rules: `docs/CODING_RULES.md`. Architecture and agent
  boundaries: `docs/ARCHITECTURE.md`.

## AI Rules

- `AIInvitationExtractor` and everything above it never know which AI
  provider is active. Only `providers/provider_factory.py` selects a
  concrete provider, and it does so at call time, not import time.
- Providers return raw text only — no JSON parsing, no validation, no
  domain objects. `AIInvitationExtractor` owns all of that.
- No hardcoded model names. Gemini's model is discovered from the live
  API and self-heals on 404, always excluding the model that just
  failed when re-discovering.
- `AI_PROVIDER` defaults to `"ollama"` — local-first, no key required.
  Gemini (`gemini` or `auto`, with automatic fallback to Ollama) is
  always an explicit opt-in, never a silent default.
- Full detail: `docs/05_AI_GUIDELINES.md`.

## Playwright Rules

- Never guess a selector or a completion signal. Capture real DOM/
  network behavior first.
- Prefer `expect_response`/`expect_download` (real event signals) over
  any DOM heuristic.
- `wait_for_timeout()` and bare `time.sleep()` are banned in
  application code.
- Full detail: `docs/06_PLAYWRIGHT.md`.

## UI Rules

- PySide6 UI (`ui/`) coordinates agents/workers only — no parsing, no
  Playwright calls, no direct AI SDK calls, no business logic.
- Network-bound work (AI calls, browser automation) always runs off
  the Qt main thread via a `QObject` worker + `QThread`, reporting
  through signals — never blocks the window.
- Raw SDK/API exceptions never reach the user. Translate to a friendly
  message at the UI boundary (`ui/messages.py`).
- Settings persist through `config_store.set_config_value` — the one
  place that writes `.env` and updates the in-process `config` module,
  so changes take effect without an app restart.

## Testing Rules

- Four tiers, lowest-risk first: `py_compile`, FakePage tests, local
  Playwright tests, real VBĐH tests. Real VBĐH and real external APIs
  (Gemini) require explicit case-by-case authorization before the
  first real call.
- Every modified `.py` file compiles clean before review.
- Mock external SDKs in unit tests — never call a real API in the
  default test run.
- Full tiers and commit-gating rules: `docs/TESTING.md`.

## Git Rules

- Never commit or push without a separate, explicit instruction — see
  Approval Workflow above.
- One logical change per commit.
- Show a diff summary scoped to the approved files before any commit
  is proposed.
- Never use `--no-verify`, force-push, or bypass signing unless
  explicitly instructed.

## Reporting Template

Every completed task reports, in this order:

1. **Files changed** — new vs. modified, one line each.
2. **Test results** — what ran, what passed/failed, which tier.
3. **Integration/real-world results** — if a real API, browser, or
   external service was exercised, what was actually observed.
4. **Git diff summary** — scoped to the approved files.
5. Explicit confirmation: no commit, no push, unless instructed
   otherwise for this task.

## Documentation Map

| Doc | Covers |
|---|---|
| `docs/ARCHITECTURE.md` | System architecture, agent responsibilities, hard rules |
| `docs/CODING_RULES.md` | Coding standards, scope discipline |
| `docs/TESTING.md` | Testing tiers, commit workflow |
| `docs/PROJECT_STATUS.md` | What's implemented today |
| `docs/AGENT_GUIDE.md` | Quick per-component reference |
| `docs/DEVELOPMENT.md` | High-level development pipeline |
| `docs/CHANGELOG.md` | Project history |
| `docs/02_WORKFLOW.md` | Feature/bug/refactor workflows, approval, budgets |
| `docs/05_AI_GUIDELINES.md` | Full AI provider architecture |
| `docs/06_PLAYWRIGHT.md` | Browser automation rules and patterns |
| `docs/09_LESSONS_LEARNED.md` | Concrete lessons from this project |
| `docs/10_ADR.md` | Architecture decision records |

When a request's detail lives in one of these docs, follow that doc —
this file is the map, not the territory.
