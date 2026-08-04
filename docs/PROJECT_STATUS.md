# GovCopilot — Project Status

This is the single source of truth for the current implementation status
of GovCopilot. It reflects project capability only — what the system can
actually do right now, not what has or hasn't been committed to git.

## Completed

- **InvitationReader** (`parser/invitation_reader.py`) — reads a meeting
  invitation PDF or DOCX file and returns its plain text.
- **DocumentExtractorAgent** (`agents/document_extractor.py`) — extracts
  every referenced document number (Tờ trình / Báo cáo / Công văn) from
  invitation text.
- **MeetingParserAgent** (`agents/meeting_parser.py`) — parses invitation
  text into a structured `Meeting` object: title, chairman, date, time,
  location, participants, agenda items, and referenced documents (via
  `DocumentExtractorAgent`).
- **BrowserSession** (`browser/login.py`) — opens and manages a
  persistent, VBĐH-authenticated Playwright browser session (open,
  close, get the active page), backed by a profile that carries a
  manual login across runs.
- **Developer tooling** — a page-state discovery script and an Alt+Click
  selector-inspection tool, used to capture real VBĐH page state and
  element selectors for agent development.
- **`docs/ARCHITECTURE.md` and `docs/CODING_RULES.md`** — the governing
  architecture and coding-rules documents for the project.

## Current Sprint

- **VBSearchAgent** (`agents/vb_search.py`) — can navigate to the VBĐH
  search page and submit a search for a document number using verified
  selectors, and reports whether the search request itself succeeded.
  It does not yet determine whether a matching document was found, open
  a result, or return a document link — that requires a verified,
  generic result-row selector, which has not yet been captured.

## Upcoming Sprint

- Complete `VBSearchAgent`: capture a generic result-row selector from
  the real VBĐH UI, implement opening/matching a search result, and
  return the document's detail link.

## Planned

- **DownloadAgent** — download attachments, update `MeetingDocument`
  status.
- **ReviewAgent** — AI review of downloaded documents.
- **ProposalAgent** — generate the advisory report from `ReviewAgent`
  output.
- **ExportAgent** — generate the final Word report.

## Known limitations

- `VBSearchAgent` cannot yet confirm whether a document was actually
  found in VBĐH, nor return a usable document link — only that the
  search request completed.
- No agent has been exercised against a real, authenticated VBĐH
  session.
- `BrowserSession.open()` always shows a manual login prompt and blocks
  for input; there is no automated re-authentication or
  authenticated-state detection, so it cannot run unattended yet.
- The pipeline has no capability past search — no `DownloadAgent`,
  `ReviewAgent`, `ProposalAgent`, or `ExportAgent` exists yet.
