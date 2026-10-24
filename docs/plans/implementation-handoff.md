# AI Station implementation handoff

The full platform goal stays active. Work on useful general local agents and
conversation-first workflows; standalone IDE/external coding expansion remains
deferred. Preserve existing services and records. No subagents, unapproved model
downloads, driver changes, public exposure or main/master operations.

## Authoritative live state — 2026-10-24

PR #402 is merged to develop as `e05d1c624cd128c8f96fc08e1956c26fa0c4110c`,
reviewed source `e434d659d62a02591955b74529b64ff057de1ff9`.
Release: `.tools/ui-agent-rendered-research-20261024`.
The source/image/backup/launcher authority is
`data/acceptance/safety-redeploy-20261012/deployment.json`; inspect it before
another rollout. LAN UI: http://192.168.1.121:8765 (password preserved).
Qualification: `data/acceptance/agent-rendered-research-20261024/post-deployment-qualified.json`.

Delivered: persistent local-code/Python agents can use reviewed Browser sources.
The exact original raw capture, compact projection, URLs, workflow and deadline
are bound before local work. Source UI includes rendered text/screenshots without
claiming pixel inspection. Actual public JavaScript page → Local Auto 131072
context → native offline Python returned the independently checked count 10.
The existing bounded repair used two Python attempts. An initial QA marker was
absent from the page and correctly returned zero; that rejected test assumption
and proof are retained separately. Original model/GPU/cache/context restored,
native PID unchanged, QA agents paused, original checkout preserved.

Full gate: 3218 Python/Runner cases (3209 passes/nine explicit opt-in skips),
718 UI tests, Ruff, UI format/lint/types/build, exact image/backend/assets and
normal/dev/private-LAN Compose. Compiled 1440/390 actual API/SQLite/disposable Git
acceptance used fake Browser/model/Python; actual live integration is separate.
No operator-inbox mail qualification is claimed.

PR #401 (`d00887d`, reviewed `df215f9`) is also deployed/qualified. Queued consumers
may yield their managed model for verified media prerequisites and restore the
exact preset through ordinary preparation/load Runs. Active/unrelated consumers
remain protected; Stop, expiry, recovery and shared startup have coverage. Its
3190 Python passes/nine skips and source-identical 716 UI qualification are in
`data/acceptance/dependent-consumer-eviction-20261024/post-deployment-qualified.json`.
Do not rebuild that eviction/reload engine or claim a new real GPU handoff smoke.

## Next owned task

Branch `feat/conversation-rendered-data`, `.tools/conversation-rendered-data`,
based on develop #402. Read [direct rendered data](conversation-rendered-data.md).
Reuse the now-qualified Browser → source handoff → offline data pipeline directly
from Chat/Work's explicit Data controls, without creating a persistent Agent.

Implementation is in progress; live remains #402 until new qualification.
The original regression failed because `DataResearchSelection` rejected the new
`render_pages` field. The candidate now adds typed scope/legacy serialization,
exact root permissions, native prepare/final-adoption binding and an explicit
composer option. First actual worker/temporary-DB/fake-runner Chat and Work cases
pass; relevant existing Browser/static-data and UI cases also pass.
Normal full gates, compiled desktop/mobile, review/PR/deployment remain required.

Original boundaries to preserve in review:
conversation data roots previously required exact fixed `data_agents.REQUIRED`;
`reviewed_research_step` previously permitted only agent_tool network_read sources; native
Browser payload/finish treats missing agent_id as a standalone URLs request.
Update these together using the existing prepare hook and final source binding.
Preserve old request receipt serialization by omitting a false new option.
Do not broaden ordinary Web permission or automatic routing implicitly.

## Preserved work and operations

Root checkout `feat/memory-scope-tagged-runs` at `6ba096d` has original README,
architecture, Memory docs/UI/tests and handoff WIP. Leave it untouched; that
functionality was already ported in #319. Use owned feature/release worktrees.
Keep .venv/node_modules links untracked. Node runtime:
`.tools/node-runtimes/node-v22.23.3-linux-x64/bin`.

Read AGENTS.md and architecture/security/README. Complete local checks replace
manual hosted Actions under the explicit account-credit exception; failing tests
are not waived. Full diff self-review and satisfactory checks precede squash
merge to develop. Controller restarts are authorized; unchanged Runner/model
should stay running. Back up and preserve IDs/auth/definitions/due instants.
Whisper-small download consent remains pending. Do not infer its approval.

The [product ledger](../product-completion.md) retains full scope and acceptance.
The [agent-first direction](agent-first-product.md) supersedes IDE expansion.
This handoff replaces a long historical timeline for efficient continuation;
[all earlier notes remain preserved](implementation-handoff-history-20261024.md).
Historical current/next labels there are evidence, not new instructions.
