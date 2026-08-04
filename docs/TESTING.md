# GovCopilot — Testing

This document describes the testing workflow used in GovCopilot
development: four testing tiers of increasing risk, a guideline for
choosing between them, hard "never" rules, and the commit workflow that
gates when code can be proposed for commit. It is a process document —
it describes how testing works here, not a record of specific past runs.

## Testing tiers

### 1. `py_compile`

- **Purpose:** catch syntax errors before any other check.
- **When to use:** every modified `.py` file, always, first.
- **What it verifies:** the file parses and compiles.
- **What it does NOT verify:** correct behavior, imports resolving at
  runtime, or logic correctness.

### 2. FakePage tests

- **Purpose:** verify agent control flow and Playwright call sequence
  without a browser.
- **When to use:** testing agents that drive a Playwright `Page` object
  (e.g. `VBSearchAgent`), especially error-handling and
  batch-continuation behavior.
- **What it verifies:** the exact call sequence and arguments made
  against the page object, and behavior under simulated failures.
- **What it does NOT verify:** that the code works against a real
  page's real DOM, or that the selectors it uses actually exist on the
  live site.

### 3. Local Playwright tests

- **Purpose:** verify real browser/JS runtime behavior that a fake
  object can't simulate.
- **When to use:** testing injected JavaScript, event listeners, DOM
  traversal, or storage behavior (e.g. `tools/selector_discovery.py`).
- **What it verifies:** real browser execution of the code's JS/DOM
  logic, in isolation.
- **What it does NOT verify:** anything about the real VBĐH site — the
  test fixture doesn't represent VBĐH's actual markup, and this tier
  deliberately avoids the persistent profile and the live site.

### 4. Real VBĐH tests

- **Purpose:** verify behavior against the actual live system.
- **When to use:** only when a lower-risk tier cannot answer the
  question — for example, confirming that real VBĐH markup or selectors
  exist, validating real authenticated navigation, or a final
  end-to-end check before relying on a workflow in production. Always
  requires explicit case-by-case authorization first, since this is a
  live production government system.
- **What it verifies:** real end-to-end behavior, for whatever was
  actually exercised in that run.
- **What it does NOT verify:** anything beyond what was actually run
  and observed — a passing run at one point in time does not guarantee
  the same behavior for other documents, sessions, or future site
  changes.

## Selection guideline

- Always choose the lowest-risk testing tier that can verify the
  change.
- Escalate to a higher-risk tier only when necessary.

## Never

- Never run Real VBĐH tests without approval.
- Never run the whole project's test suite unless requested.
- Never commit before focused tests pass.
- Never push without approval.

## Commit workflow

- `py_compile` must pass on every modified file.
- Focused tests (FakePage and/or Local Playwright, whichever applies)
  must be run and shown before any commit is proposed — never the
  whole project's suite unless explicitly asked.
- Test results, files changed, known limitations (where applicable),
  and a git diff summary are shown for review before commit.
- A commit happens only after a separate, explicit approval distinct
  from implementation approval — approving the implementation is not
  approval to commit.
- Staging is scoped to exactly the approved file(s) — never a broad
  `git add -A` / `git add .`, so unrelated pending changes are never
  swept in.
- Pushing requires its own separate, explicit instruction.
