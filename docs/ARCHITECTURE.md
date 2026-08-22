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
InvitationReader -> MeetingParserAgent -> VBSearchAgent -> DownloadAgent -> NormalizationAgent -> NDContentExtractor -> ReviewAgent -> ProposalAgent -> ExportAgent
```

1. **`parser/invitation_reader.py` (`InvitationReader`)** reads the raw
   PDF/DOCX invitation file and returns plain text. This is the **only**
   PDF/DOCX parsing implementation in the codebase — other components
   needing a file's text (e.g. `NDContentExtractor`) call its functions
   directly rather than re-implementing parsing.
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
   same `Meeting` object. Two independent download paths, same
   contract: `download()` (VBĐH, via an already-open Playwright dialog)
   and `download_from_drive()` (a shared Google Drive folder, via
   `agents/drive_client.py` — API key only, no OAuth). Which path runs
   for a given document, and how a Drive folder ID is resolved for it,
   is not yet wired into this pipeline stage — see ADR-011.
5. **`NormalizationAgent`** groups downloaded documents by agenda item
   (ND, via `MeetingDocument.agenda_item_index`), bundling each group
   into a `NDxx.zip` + `NDxx.meta.json` pair, ready for AI review.
6. **`NDContentExtractor`** (`ai/nd_extractor.py`) reads each
   `NDxx.zip`/`NDxx.meta.json` bundle and asks Gemini (via `AIProvider`)
   to extract its content faithfully — no summarizing, no analysis —
   saved as `NDxx.extract.md`. Only NDs where every file has a real
   text layer are processed; a scanned/unsupported/empty file skips
   that whole ND (logged, never a crash). See ADR-012.
7. **`ReviewAgent`** collects externally-produced AI review results
   (`NDxx.review.md`) — performs no AI analysis itself.
8. **`ProposalAgent`** uses AI to draft advisory proposals from the
   reviewed documents.
9. **`ExportAgent`** generates the final Word advisory report from the
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
- The only PDF/DOCX *parsing implementation* in the codebase — other
  components call its functions (`read_pdf`/`read_docx`/`read_invitation`)
  directly rather than re-implementing parsing themselves.

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
**Module:** `agents/download.py`
- Download attachments, from either VBĐH (`download()`) or a shared
  Google Drive folder (`download_from_drive()`).
- Update `MeetingDocument` status — both paths mutate
  `MeetingDocument.downloaded`/`local_path` identically, so downstream
  agents never need to know which source a document came from.
- Never search documents, VBĐH or Drive: `download_from_drive()` takes
  an already-resolved Drive folder ID; it doesn't decide which folder
  a document belongs to.
- Drive HTTP transport lives in `agents/drive_client.py`
  (`list_folder`/`download_binary`/`export_native_file`, plus
  `DriveApiError`/`DriveForbiddenError`/`DriveNetworkError`) —
  transport-only, same provider/consumer split as `providers/` for AI.
  `DownloadAgent` owns all folder-traversal and document-matching
  decisions; `drive_client` never does. See ADR-011.

### NormalizationAgent
**Module:** `agents/normalization.py`
- Group downloaded `MeetingDocument`s by agenda item (ND), using
  `MeetingDocument.agenda_item_index`.
- Bundle each group into `NDxx.zip` + write `NDxx.meta.json`.
- Identify the Tờ trình file by filename only, never by content;
  fewest-bytes-on-disk PDF/DOCX as fallback — never by page count.
- Documents whose ND couldn't be determined are grouped separately,
  never silently dropped.
- Never reads PDF/DOCX content — that stays `InvitationReader`'s
  exclusive job.
- Never searches VBĐH, never performs AI analysis.

### NDContentExtractor
**Module:** `ai/nd_extractor.py`
- For each `NormalizedAgendaGroup`, read its `NDxx.zip`'s real file
  list (never `NDxx.meta.json`'s `danh_sach_file`, which can drift from
  the zip's actual contents) and extract every file's text via
  `parser/invitation_reader.read_invitation()` — the only PDF/DOCX
  parsing implementation in the codebase (see `InvitationReader` above).
- Ask Gemini (via `AIProvider`/`ProviderFactory`, same as
  `AIInvitationExtractor`) to extract that content faithfully — no
  summarizing, no analysis, no opinion — saved as `NDxx.extract.md`.
  Does zero response parsing: the raw text *is* the output.
- A scanned PDF (no extractable text), an unsupported file type, or a
  missing/empty bundle skips that ND entirely — per-ND, all-or-nothing,
  logged, never a crash and never a partial extraction. See ADR-012.
- Never performs the second-tier 6-section analysis — that stays
  outside the codebase, per `ReviewAgent`'s contract below, unchanged.

### ReviewAgent
**Module:** `ai/review.py`
- Collect AI review results produced *outside* this codebase — a human
  runs each `NDxx.zip` bundle through ChatGPT web via a Cowork session
  (manual/semi-automated, deliberately outside Python app control) and
  saves the result as `NDxx.review.md` in the reviews directory.
- For each `NormalizedAgendaGroup`, read the matching
  `NDxx.review.md` if it exists; otherwise report the group as not yet
  reviewed.
- Never calls an AI provider. Never touches Playwright or a browser.
- A missing review file is a normal, expected mid-workflow state, not
  an error — logged at INFO, never WARNING.

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
- **No agent implements its own PDF/DOCX parsing.** All PDF/DOCX-to-text
  conversion lives in exactly one module, `parser/invitation_reader.py`
  (`read_pdf`/`read_docx`/`read_invitation`) — any component needing a
  file's text calls these functions rather than writing its own parser.
  `MeetingParserAgent` calls it once per invitation, upfront;
  `NDContentExtractor` (`ai/nd_extractor.py`) calls it per file inside
  an already-downloaded `NDxx.zip` bundle. Both are legitimate callers
  of the same shared module — the rule is "one parsing implementation,"
  not "one caller."
- **One `Meeting` object per pipeline run.** Each stage receives and
  returns (or mutates) the same `Meeting` instance — no stage constructs a
  parallel, divergent representation of the same data.
- **`ReviewAgent` never calls an AI provider or a browser.** The ChatGPT
  interaction happens outside this codebase (a Cowork session), by
  deliberate architecture decision — avoids the ToS risk of automating
  the ChatGPT web UI (see the design discussion this decision came
  from).

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
