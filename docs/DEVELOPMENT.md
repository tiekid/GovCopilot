# GovCopilot — Development Workflow

This document describes the development workflow used in this project.
It does not duplicate `docs/ARCHITECTURE.md`, `docs/CODING_RULES.md`,
`docs/PROJECT_STATUS.md`, `docs/CHANGELOG.md`, or `docs/TESTING.md` —
it references them where their detail applies.

## Development workflow

```
Plan
  ↓
Approval
  ↓
Implementation
  ↓
py_compile
  ↓
Focused tests
  ↓
Review
  ↓
Commit approval
  ↓
Commit
  ↓
Push approval
  ↓
Push
```

See `docs/TESTING.md` for what `py_compile` and focused tests mean, how
to choose a testing tier, and the hard "Never" rules around testing.

## Scope control

- Modify only approved files.
- Never expand scope without approval.
- Preserve existing architecture.
- Reuse existing code whenever possible.
- Prefer extending existing modules over creating new ones.
- Never redesign architecture without explicit approval.

See `docs/ARCHITECTURE.md`'s "Architectural governance" section and
`docs/CODING_RULES.md` for the full rules these summarize.

## Commit policy

- One logical change per commit.

Staging scope, review requirements, and push approval are defined once,
in `docs/TESTING.md`'s "Commit workflow" and "Never" sections — not
repeated here.

## Documentation policy

Whenever architecture, workflow, testing strategy, coding rules, or
agent responsibilities change, update the corresponding documentation
before adding new features.

Reference existing documents instead of duplicating them:

- `docs/ARCHITECTURE.md` — architecture and workflow
- `docs/CODING_RULES.md` — coding standards
- `docs/PROJECT_STATUS.md` — implementation status
- `docs/CHANGELOG.md` — project history
- `docs/TESTING.md` — testing tiers and workflow
- `docs/AGENT_GUIDE.md` — quick-reference component responsibilities
