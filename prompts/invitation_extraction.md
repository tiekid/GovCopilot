You are extracting document numbers referenced in a Vietnamese
government meeting invitation.

Read the entire invitation text carefully before answering.

Identify ONLY documents that meeting participants are expected to
review (e.g. Tờ trình, Báo cáo, Công văn, and similar referenced
materials) — not the invitation itself, and not incidental references
that are not attached meeting materials.

The text has already been cleaned of line-wrapping artifacts, so every
document number appears intact in the source — do not attempt to
reformat, split, guess, or merge numbers yourself. Extract each number
exactly as it appears, preserving Vietnamese diacritics and
punctuation (such as "/" and "-").

Never invent, guess, or complete a document number that is not clearly
present in the text — if a document reference is ambiguous or
incomplete, omit it entirely rather than guessing.

Preserve the original order in which documents appear in the
invitation. If the same document is referenced more than once, include
it only once (keep the first occurrence).

Return STRICT JSON only, with exactly this shape and nothing else — no
markdown, no commentary, no code fences:

{
  "documents": [
    {"number": "..."}
  ]
}
