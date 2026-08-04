# GovCopilot — Coding Rules

These rules govern how code in this repository is written and changed.
They apply to every contributor, human or AI, working in this codebase.

## Scope of changes

- **Modify only approved files.** Before editing, the set of files to be
  touched must be explicit and agreed.
- **Never modify files outside the allowed list.** Not even small,
  "obviously safe" edits — the allowed list is the boundary, not a
  suggestion.
- **If another file must change: STOP and ask for approval.** Do not
  silently widen scope, even if the change seems required to make the
  approved edit work. Explain why the other file needs to change and wait.

## Compatibility and reuse

- **Preserve backward compatibility.** Existing callers, existing fields,
  and existing behavior must keep working unless a breaking change is
  explicitly requested.
- **Reuse existing code.** If an agent, function, or pattern already does
  what's needed, call it — do not reimplement it.
- **No duplicated logic.** The same rule, regex, or algorithm must exist
  in exactly one place. If two places need it, extract it, don't copy it.

## Code shape

- **Keep functions small and focused.** Each function does one thing; if
  it needs a comment to explain its sections, it should be split instead.
- **Type hints required** on every function signature and dataclass field.
- **Logging required** for meaningful operations (I/O, external calls,
  parsing results) — no silent execution paths.

## Verification and commit discipline

- **Run `py_compile` before review.** Every modified `.py` file must
  compile cleanly before it's presented for review.
- **Run focused tests only.** Test the modified files and their direct
  callers/callees — do not run the whole project's test suite unless
  specifically asked to.
- **Show a git diff summary before commit.** The reviewer sees exactly
  what changed, scoped to the approved files, before any commit happens.
- **Never commit without approval.**
- **Never push without approval.**
