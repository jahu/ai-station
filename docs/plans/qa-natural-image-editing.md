# Natural edits retain the verified image source

Browser QA found explicit follow-ups such as “Zmień kolor roweru na niebieski…
użyj poprzedniego zdjęcia jako źródła” and editing a square “w poprzednim
załączonym obrazku” routed to ordinary chat. The model described a fake edited
image rather than executing the image adapter.

Recognize a direct editing command whose image location/source appears later
in the instruction, not only the exact “Edit this image: …” template. Strip
quoted/code examples for routing, retain the original full instruction for
generation, and keep advice, explicit code/document/prompt edits outside this
rule. The existing same-conversation resolver still selects and verifies the
completed image or successfully inspected input. Missing, ambiguous, trashed,
unfinished or changed sources still fail closed. Explicit tool/input/worktree
choices remain authoritative; this does not inspect another conversation or
let model prose select an artifact.

Acceptance requires real WORK-004 and UNIFIED-001 browser follow-ups after
deployment: a new image Run, the correct source artifact and preserved original,
a real downloadable edited image in the conversation, and visual inspection of
the requested change. Source-selection unit tests do not prove image quality.
