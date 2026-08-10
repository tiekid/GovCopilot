# GovCopilot — Development Workflows

This document defines the workflow for each kind of task, plus the
approval gates and budgets that apply within any workflow. It extends
`docs/DEVELOPMENT.md`'s high-level pipeline (Plan → Approval →
Implementation → py_compile → Focused tests → Review → Commit approval
→ Commit → Push approval → Push) with per-task-type detail.

## Feature workflow

1. **Plan.** Read the relevant governing docs (`docs/ARCHITECTURE.md`,
   `docs/CODING_RULES.md`) and the code the feature actually touches.
   State the file list explicitly.
2. **Approval.** Wait for explicit sign-off on the file list and
   approach before writing code. A design decision with real
   trade-offs is presented as a recommendation with rationale, not an
   open-ended menu — but it still waits for confirmation if it changes
   scope.
3. **Implementation.** Smallest change that satisfies the requirement.
   Reuse existing agents/providers/models before introducing new ones.
4. **Verify.** `py_compile` every modified file, then focused tests
   (see `docs/TESTING.md`).
5. **Report.** Files changed, test results, diff summary — see
   `CLAUDE.md`'s Reporting Template.

## Bug investigation workflow

1. **Reproduce or instrument.** If the bug can be reproduced locally
   with a fake/mock, do that first — cheapest, fastest. If it requires
   a real system (VBĐH, a real AI API), instrument the code to capture
   evidence — logs, diagnostic JSON, exact raw request/response —
   rather than guessing at a fix blind.
2. **Evidence, not guesses.** Do not change behavior until the
   evidence is in hand. See the `DownloadAgent` diagnostic
   instrumentation and the Gemini 404 investigation in
   `docs/09_LESSONS_LEARNED.md` for the pattern this project follows.
3. **Verify a claimed bug before fixing it.** "This looks hardcoded" or
   "this is wrong" is a hypothesis, not a fact, until checked against
   the actual code and the actual system's real behavior — a claimed
   bug sometimes turns out to be correct behavior with an unexpected
   cause elsewhere (see `docs/09_LESSONS_LEARNED.md`'s "Evidence
   before implementation").
4. **Minimum fix.** Implement only what the evidence supports. Resist
   fixing adjacent things not shown to be broken.
5. **Regression test.** Every fixed bug gets a test that reproduces
   the originally observed failure mode, not just the happy path.
6. **Report**, same template as Feature workflow.

## Refactor workflow

1. **State the invariant.** What behavior must stay identical? Say it
   explicitly before touching code (e.g. "DownloadAgent's click/save
   sequence is unchanged; only observation is added").
2. **No behavior change bundled with structure change.** If a refactor
   reveals a real bug, stop and flag it separately — do not silently
   fix it inside a refactor commit.
3. **Full regression run** after, not just the tests for the touched
   file, when the refactor crosses module boundaries.
4. **Report**, same template, explicitly confirming the invariant held.

## Approval workflow

- **Two kinds of approval are never conflated:** approval to
  implement, and approval to commit/push. Each is asked for
  separately.
- **Scope creep needs its own approval.** If implementing the approved
  change requires touching a file outside the approved set, stop,
  explain exactly why, and wait — do not silently widen scope.
- **Design decisions with real trade-offs** (interface shape, default
  config values, retry/fallback semantics) are surfaced with a
  recommendation before implementing, not decided unilaterally when
  more than one reasonable option exists.
- **Real external systems** (VBĐH production, a real paid AI API key)
  always require case-by-case authorization before the first real
  call, even if the code change itself was already approved.
- **Some requests explicitly waive discussion** ("do not discuss, do
  not propose alternatives, implement directly"). When that happens,
  approval to implement is already granted for the stated scope —
  approval to commit/push is still separate and still required.

## Investigation budget

Investigation is cheap relative to implementing the wrong fix, but it
is not unlimited:

- **Prefer the lowest-risk tier that can answer the question**
  (`docs/TESTING.md`'s tier ladder: py_compile → FakePage → local
  Playwright → real VBĐH). Escalate only when a lower tier genuinely
  cannot answer it.
- **One diagnostic pass, then report.** Instrument, run it against
  enough real cases to see the pattern (typically 1–3 real examples
  per failure mode), then stop and report findings rather than
  continuing to probe indefinitely.
- **Don't guess inputs to save a round trip.** If reproducing a bug
  requires real data the agent doesn't have (a specific document
  number, a real invitation file, a real API key), ask for it rather
  than fabricating a stand-in and treating its result as evidence.
- **A live external call is a budget item, not a free action.** Every
  real Gemini/VBĐH call is logged and reported, not repeated
  speculatively (e.g. don't loop through a whole model catalog "just
  to see" — test the specific hypothesis, then stop).

## Token budget

- **Read before you plan.** Load only the files the task actually
  touches or governs — not the whole repository — before proposing a
  plan.
- **Don't re-read unchanged context.** If a file was already read this
  session and hasn't been edited since, use what's already known
  instead of re-reading it.
- **Summarize, don't paste, large evidence.** When reporting a large
  diagnostic capture (a full model list, a long stack trace), show the
  relevant excerpt plus a count/summary, not the entire raw dump,
  unless the user asked for the full text.
- **One comprehensive report beats several partial ones.** Batch
  findings from a single investigation into one report rather than
  streaming intermediate half-conclusions.
