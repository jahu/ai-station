# Useful runtime allowances in fresh natural agent drafts

The actual PR #447 five-second film took 1282 seconds. Its natural model proposal
copied the advertised 600-second runtime default; the accepted run explicitly
reviewed 7200 seconds. Existing setup suggestions work, but a fresh natural draft
should start with a useful, visible allowance without requiring advanced setup.

Make the internal proposal's maximum runtime optional/null. Tell the model to
supply a numeric value only when the current user explicitly specifies one.
Before publishing a disabled definition, resolve an omitted/null value from the
controller's existing draft defaults: 7200 seconds for Video up to 15 seconds,
14400 for longer Video, and 7200 for full Avatars, matching current setup advice.
Other kinds retain the existing deterministic draft default, including the
30-minute website build policy. Explicit numeric proposals remain authoritative
within the existing validated bounds, including deliberately short limits.

This changes only new AI-prepared disabled definitions. Public Agent settings,
existing definitions, edits, duplication and all frozen/running deadlines keep
their contracts. It must not activate an agent, alter media duration/quality,
select a memory profile, add permissions or silently apply a suggestion to an
existing agent. Source-based/selected-input proposals retain their own contracts.

Verify the actual factory prompt and stored definition, nullable/omitted values,
explicit small/large budgets, Video duration boundary, Avatar and ordinary/website
defaults. Run normal backend/Runner gates and exact image checks. Use an actual
local natural draft to check the model-facing contract; reuse PR #447's real
7200-second film only after proving executor/native/UI identity and matching
frozen settings. No additional multi-hour GPU film is needed for a draft default.
Review/merge/deploy normally; keep the whole-platform audit and final QA open.
