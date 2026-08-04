# GovCopilot — Agent Guide

This document is the quick-reference guide for every project component.

Implementation status is maintained in `docs/PROJECT_STATUS.md`.

## Relationship to other documentation

- Architecture and workflow are defined in `ARCHITECTURE.md`.
- Coding standards are defined in `CODING_RULES.md`.
- Implementation status is maintained in `PROJECT_STATUS.md`.
- This document is a quick reference for component responsibilities
  only.

## InvitationReader

**Purpose:** Read a meeting invitation file and return its plain text.

**Responsibilities:**
- Read PDF/DOCX, return plain text.
- The only PDF/DOCX reader in the codebase.

**Inputs:** A PDF or DOCX invitation file.

**Outputs:** Plain text.

**Never**
- No additional constraints beyond ARCHITECTURE.md.

## DocumentExtractorAgent

**Purpose:** Extract every referenced document number from invitation
text.

**Responsibilities:**
- Extract every referenced document number (Tờ trình / Báo cáo / Công
  văn) from invitation text.
- Used by `MeetingParserAgent`.

**Inputs:** Invitation text.

**Outputs:** Referenced document numbers.

**Never**
- No additional constraints beyond ARCHITECTURE.md.

## MeetingParserAgent

**Purpose:** Parse invitation text into a structured Meeting object.

**Responsibilities:**
- Parse invitation text.
- Build the Meeting model.
- Reuse `DocumentExtractorAgent`.

**Inputs:** Invitation text.

**Outputs:** A structured `Meeting` object (title, chairman, date,
time, location, participants, agenda items, and referenced documents).

**Never**
- Never read PDF/DOCX directly.

## BrowserSession

**Purpose:** Manage a persistent, VBĐH-authenticated Playwright browser
session.

**Responsibilities:**
- Open the persistent Playwright browser.
- Manage the browser lifecycle.
- Navigate to VB_URL.
- Return the active page.

**Inputs:** None (uses the persistent profile and configured VB_URL).

**Outputs:** The active page.

**Never**
- Never contain business logic.
- Never determine authentication state.

## VBSearchAgent

**Purpose:** Search VBĐH for each document referenced by a Meeting.

**Responsibilities:**
- Determine authentication state.
- Handle login flow when required.
- Search VBĐH using `Meeting.documents`.
- Return document links/results.
- Reuse `BrowserSession`.

**Inputs:** A `Meeting` object (`Meeting.documents`).

**Outputs:** Document links/results.

**Never**
- No additional constraints beyond ARCHITECTURE.md.

## DownloadAgent

**Purpose:** Download attachments located by `VBSearchAgent`.

**Responsibilities:**
- Download attachments.
- Update `MeetingDocument` status.

**Inputs:** Document links/results.

**Outputs:** Downloaded files; updated `MeetingDocument` status.

**Never**
- Never search documents.

## ReviewAgent

**Purpose:** AI review of downloaded documents.

**Responsibilities:**
- AI review of downloaded documents.
- Generate structured summaries.

**Inputs:** Downloaded documents.

**Outputs:** Structured summaries.

**Never**
- No additional constraints beyond ARCHITECTURE.md.

## ProposalAgent

**Purpose:** Generate the advisory report.

**Responsibilities:**
- Generate the advisory report.
- Use `ReviewAgent` output only.

**Inputs:** `ReviewAgent` output.

**Outputs:** Advisory report.

**Never**
- No additional constraints beyond ARCHITECTURE.md.

## ExportAgent

**Purpose:** Generate the final Word report.

**Responsibilities:**
- Generate the final Word report.

**Inputs:** The fully enriched `Meeting` object.

**Outputs:** The final Word advisory report.

**Never**
- Never perform AI analysis.
