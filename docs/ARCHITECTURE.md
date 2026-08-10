# GovCopilot — Architecture

GovCopilot is a desktop application for the Office of Tay Ninh Provincial
People's Committee. It reads a meeting invitation, extracts every document
referenced in it, retrieves and downloads those documents from VBĐH, has AI
summarize them, and produces a Word advisory report.

## Project structure

```
agents/     Business-logic agents (one class per business action)
browser/    Playwright-driven VBĐH automation (login, search, download)
models/     Dataclasses shared across the pipeline (Meeting, MeetingDocument, ...)
parser/     File-format reading (PDF/DOCX -> plain text)
ui/         PySide6 UI — coordinates agents, contains no business logic
ai/         AI-backed agents (review, proposal generation)
```

## Core principle: every business action is an Agent

Each unit of work is a standalone class in `agents/` (or `ai/` for
AI-backed steps). Agents are composable and independently testable. The UI
never implements business logic itself — it only calls agents and displays
their results ("UI coordinates only").

## Workflow

A single meeting invitation flows through the pipeline as one `Meeting`
object, enriched at each stage:

```
InvitationReader -> MeetingParserAgent -> VBSearchAgent -> DownloadAgent -> ReviewAgent -> ProposalAgent -> ExportAgent
```

1. **`parser/invitation_reader.py` (`InvitationReader`)** reads the raw
   PDF/DOCX invitation file and returns plain text. This is the **only**
   place in the codebase allowed to read PDF/DOCX files.
2. **`MeetingParserAgent`** (`agents/meeting_parser.py`) takes that text and
   returns a structured `Meeting` object: title, chairman, date, time,
   location, participants, agenda items, and every referenced document
   number (via `DocumentExtractorAgent`).
3. **`VBSearchAgent`** takes the `Meeting` object, uses `BrowserSession`
   (`browser/login.py`) to access the browser session — handling login
   when required — and searches for each document in `Meeting.documents`,
   resolving each `MeetingDocument` to a downloadable attachment.
4. **`DownloadAgent`** downloads every resolved attachment, updating
   `MeetingDocument.downloaded` and `MeetingDocument.local_path` on the
   same `Meeting` object.
5. **`ReviewAgent`** uses AI to summarize each downloaded document.
6. **`ProposalAgent`** uses AI to draft advisory proposals from the
   reviewed documents.
7. **`ExportAgent`** generates the final Word advisory report from the
   fully enriched `Meeting` object.

The `Meeting` object (`models/meeting.py`) is the single artifact passed
from stage to stage — no stage re-reads the source file or re-derives data
another stage already produced.

Current implementation progress for each stage is tracked in
`docs/PROJECT_STATUS.md`, not here.

## Agent Responsibilities

This is the single source of truth for what each component is (and is not)
responsible for. Each entry lists the component's module path and its
behavioral rules. Implementation status is tracked separately, in
`docs/PROJECT_STATUS.md` — not here.

### InvitationReader
**Module:** `parser/invitation_reader.py`
- Read PDF/DOCX, return plain text.
- The only PDF/DOCX reader in the codebase.

### DocumentExtractorAgent
**Module:** `agents/document_extractor.py`
- Extract every referenced document number (Tờ trình / Báo cáo / Công văn)
  from invitation text.
- Used by `MeetingParserAgent`.

### BrowserSession
**Module:** `browser/login.py`
- Launch the persistent Playwright browser.
- Reuse the persistent profile.
- Navigate to VB_URL.
- Expose the Playwright Page.
- Wait until the page is ready for further interaction (e.g. page load
  completion), and report observable session state (e.g. whether the
  persistent profile is already authenticated, whether the login page
  is still visible) — reporting only.
- Never decide what workflow should happen next.
- Never search documents.
- Never perform login.
- Never determine business logic.

### MeetingParserAgent
**Module:** `agents/meeting_parser.py`
- Parse invitation text.
- Build the Meeting model.
- Reuse `DocumentExtractorAgent`.
- Never read PDF/DOCX directly.

### VBSearchAgent
**Module:** `agents/vb_search.py`
- Determine authentication state.
- Handle login flow when required.
- Search VBĐH using `Meeting.documents`.
- Return document links/results.
- Reuse `BrowserSession`.

### DownloadAgent
**Module:** `agents/`
- Download attachments.
- Update `MeetingDocument` status.
- Never search documents.

### ReviewAgent
**Module:** `ai/review.py`
- AI review of downloaded documents.
- Generate structured summaries.

### ProposalAgent
**Module:** `ai/proposal.py`
- Generate the advisory report.
- Use `ReviewAgent` output only.

### ExportAgent
**Module:** `agents/`
- Generate the final Word report.
- Never perform AI analysis.

## Hard rules

- **UI coordinates only.** `ui/main_window.py` may call agents and render
  their output; it must not parse text, call Playwright, or call the
  OpenAI API directly.
- **Agents never read PDF/DOCX directly.** Only `parser/invitation_reader.py`
  touches file formats. Every agent downstream of it operates on the
  `Meeting` object or plain text already extracted from it.
- **One `Meeting` object per pipeline run.** Each stage receives and
  returns (or mutates) the same `Meeting` instance — no stage constructs a
  parallel, divergent representation of the same data.

## Architectural governance

- **Preserve existing architecture.** Changes extend the structure defined
  in this document; they do not introduce parallel structures or bypass
  the agent boundaries above.
- **Prefer adapting existing code over redesigning it.** When a new
  requirement can be met by extending an existing agent, model, or module,
  do that instead of introducing a new abstraction or restructuring what
  already works.
- **This document governs future architectural decisions.** Any change to
  the workflow, agent responsibilities, or the rules above must update
  this document first; code should not drift from what is written here.
