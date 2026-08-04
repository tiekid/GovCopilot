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
3. **`VBSearchAgent`** *(planned, Sprint 2)* takes the `Meeting` object,
   logs into VBĐH (`browser/login.py`), and searches for each document in
   `Meeting.documents`, resolving each `MeetingDocument` to a downloadable
   attachment.
4. **`DownloadAgent`** *(planned, Sprint 3)* downloads every resolved
   attachment, updating `MeetingDocument.downloaded` and
   `MeetingDocument.local_path` on the same `Meeting` object.
5. **`ReviewAgent`** *(planned, Sprint 4)* uses AI to summarize each
   downloaded document.
6. **`ProposalAgent`** *(planned, Sprint 4)* uses AI to draft advisory
   proposals from the reviewed documents.
7. **`ExportAgent`** *(planned, Sprint 5)* generates the final Word
   advisory report from the fully enriched `Meeting` object.

The `Meeting` object (`models/meeting.py`) is the single artifact passed
from stage to stage — no stage re-reads the source file or re-derives data
another stage already produced.

## Agent Responsibilities

This is the single source of truth for what each component is (and is not)
responsible for. Module/status metadata and behavioral rules live together,
per component, so there is one place to update when either changes.

### InvitationReader
**Module:** `parser/invitation_reader.py` · **Status:** Implemented
- Read PDF/DOCX, return plain text.
- The only PDF/DOCX reader in the codebase.

### DocumentExtractorAgent
**Module:** `agents/document_extractor.py` · **Status:** Implemented
- Extract every referenced document number (Tờ trình / Báo cáo / Công văn)
  from invitation text.
- Used by `MeetingParserAgent`.

### BrowserSession
**Module:** `browser/login.py` · **Status:** Implemented
- Open the persistent Playwright browser.
- Manage the browser lifecycle.
- Navigate to VB_URL.
- Return the active page.
- Never contain business logic.
- Never determine authentication state.

### MeetingParserAgent
**Module:** `agents/meeting_parser.py` · **Status:** Implemented
- Parse invitation text.
- Build the Meeting model.
- Reuse `DocumentExtractorAgent`.
- Never read PDF/DOCX directly.

### VBSearchAgent
**Module:** `agents/` *(planned, Sprint 2)* · **Status:** Not started
- Determine authentication state.
- Handle login flow when required.
- Search VBĐH using `Meeting.documents`.
- Return document links/results.
- Reuse `BrowserSession`.

### DownloadAgent
**Module:** `agents/` *(planned, Sprint 3)* · **Status:** Not started
- Download attachments.
- Update `MeetingDocument` status.
- Never search documents.

### ReviewAgent
**Module:** `ai/review.py` *(planned, Sprint 4)* · **Status:** Not started
- AI review of downloaded documents.
- Generate structured summaries.

### ProposalAgent
**Module:** `ai/proposal.py` *(planned, Sprint 4)* · **Status:** Not started
- Generate the advisory report.
- Use `ReviewAgent` output only.

### ExportAgent
**Module:** `agents/` *(planned, Sprint 5)* · **Status:** Not started
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
