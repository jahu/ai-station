# Auto Local Coding for persistent agents

New natural-language coding-agent drafts select Auto Local Coding, matching the
Coding and create-project/build defaults. A report-only agent retains its chosen
response model, and an external coding agent retains CLI default selection.
Existing saved local agent models are preserved. The definition editor offers
Auto or an explicit model for local coding; changing a selection never loads it.

Enabling an Auto coding agent checks a fitting observed local GGUF with at least
100k context using the shared router. Its actual coding dispatch rechecks fit and
records the selected model/context/devices; no small-chat or cloud fallback is
allowed. Approval still precedes owned runtime loading and worktree preparation.
Auto is a coding policy, not a pretend provider model name used for inference.
