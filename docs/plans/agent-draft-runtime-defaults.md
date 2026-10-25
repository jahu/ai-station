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

## Qualification

Current normal coverage is 4141 cases: 4132 pass and nine integrations remain
explicitly opt-in. The complete frozen baseline passed 4131 and retained one
failure: an older assertion expected 600 on the internal Proposal object.
That object now deliberately defers with null. The corrected test checks the
resolved ordinary definition still has 600 and an explicit 7200 stays exact.
Both complete final budget/media modules pass all 39 cases; all other Python
source/test modules are unchanged and per-function collected case counts match.
The original failed baseline is retained, not relabelled. This combined local
gate avoids rerunning unchanged modules and waives no test failure.

Actual isolated Qwen3.5 9B returned null for the unspecified allowance, producing
a disabled 7200-second/five-second-video definition; an explicit five-minute
limit returned and retained 300. Both drafts remain disabled. No agent or media
workload was executed for this check; its owned inference runtime was stopped.
Compiled 1440px/390px Settings and reload show the exact saved 7200/300 values,
create no Runs and have no overflow or JavaScript errors. This is viewport
coverage, not a physical-phone claim. The existing film proof retains its own
bounded-memory profile and does not qualify every proposed video setting.

Ruff, exact image/backend/assets, three Compose variants and isolated image
API/worker/SQL/SSE/reopen are checked for the final candidate. Frontend/native
source is unchanged, retaining the qualified 844-test frontend. Catalog v10 adds
AGENT-014 and keeps the other 156 IDs; eight offline QA-export checks pass.
Exact tested/reviewed/image mappings and deployment authority remain under
`data/acceptance/agent-draft-runtime-defaults-20261025/`.
