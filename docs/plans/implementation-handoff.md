# AI Station implementation handoff

The full platform goal stays active. Prioritize useful local agents and
conversation-first workflows; standalone IDE/external coding expansion is deferred.
No subagents, unapproved model downloads, driver changes, public exposure or
main/master operations. Preserve existing services, user records and root WIP.

## Authoritative live state — 2026-10-24

PR #405 merged to develop as `7ea7da9a321fa007a49751eac22548227a7a506f`, reviewed
source `6748bf350199fa9f296e92c9a8c767b2db87f871`. Controller release:
`.tools/ui-data-output-declarations-20261024`. LAN UI: http://192.168.1.121:8765.
The deployment/image/backup authority remains
`data/acceptance/safety-redeploy-20261012/deployment.json`.
Qualification: `data/acceptance/data-output-declarations-20261024/post-deployment-qualified.json`.

Delivered: instruction-only CSV/Excel/PNG/text creation in Chat/Work and persistent
Python agents, explicit Files & data controls, natural clear first Send, generated
workbook reuse and original input preservation. Actual normal-worker local model
at 131072 context created exact independently checked ten-row CSV/XLSX and PNG in
one Python attempt. Operator preset restored; ready instance now
`7668f4c4-7da0-41d9-afcb-265205a8f76d`. QA conversation
`f0f36541-0e2b-46bc-acb9-d5c69f707e72` archived. No Agent was created.

Native service PID `2626257` stays unchanged in
`.tools/ui-echo-memory-profile-20261024`, source fingerprint
`83eee0fc6ffc234ab185a4fb15fbc03cedd5846f57f1c21dca5e45057ab20644`.
Socket remains0600; schema0033, auth/IDs/agent definitions/due instants preserved.
All QA agents are paused. Query actual live state before another rollout.

Full #405 gate: 3289 Python/Runner cases (3280 pass/nine opt-in skips), Ruff,
724 UI tests reused under exact unchanged frontend-source comparison, exact Docker
backend/assets, three Compose configurations and new compiled1440/390 API/SQLite
flows. CPU replay of the original real-model response also verifies bounded
intentional repair, all ten CSV/XLSX rows, PNG and workbook follow-up total55.
The first #404 actual-model test failed because its manifest redundantly listed
mandatory CSV/JSON. That failed evidence remains under
`data/acceptance/local-file-creation-20261024`; #405 corrects it without expanding
the output allowlist or adding model calls. Do not relabel the failure.
Remote merged #404/#405 feature branches were deleted after qualification.

Earlier rendered public-page/local-code/data, agent result-email, owned model
restoration and media deliveries remain recorded in
[product status](../product-completion.md) and the preserved
[historical handoff](implementation-handoff-history-20261024.md).
Do not repeat their GPU jobs or treat historical next labels as new work.

## Current owned increment

Branch `feat/file-creation-conversation-context`,
`.tools/file-creation-conversation-context`, based on #405.
Read [creation context](file-creation-conversation-context.md).
The actual API/worker regression proved plain prior conversation values were lost
before generation. Initial red evidence:
`data/acceptance/creation-conversation-context-red.log`.

Candidate adds bounded same-conversation plain-text snapshots with source IDs,
hashes and explicit omission/excerpt flags, bound on current message/root Run.
The existing data definition quotes the text to the local generator; current goal
retains priority and no files/permissions/URLs are inherited. Worker scope/source
validation precedes execution. Chat's collapsed context note exposes the exact
text without active HTML. No native, schema or dependency changes.

Seventy focused backend cases and20 related UI tests/types pass. Full-source
gates are next; inspect their actual handles/logs before restarting. Complete full gates, exact image/compiled UI,
review and develop rollout, then a small real-context creation qualification.
Live remains #405 until the next post-deployment-qualified report passes.

## Operations and preserved work

Root `feat/memory-scope-tagged-runs` at `6ba096d` retains original README,
architecture, Memory docs/UI/tests and handoff WIP. Do not edit/reset it; that
functionality was already ported in #319. Keep .venv/node_modules links untracked.
Node: `.tools/node-runtimes/node-v22.23.3-linux-x64/bin`.
Read AGENTS.md and architecture/security/README. Complete local checks replace
manual hosted Actions under the user-approved account-credit exception; actual
failures are never waived. Full diff review and satisfactory checks precede squash
merge to develop. Controller restarts are authorized; preserve unchanged Runner
and model. Back up before rollout. Whisper-small consent remains pending; do not
infer a download approval. No operator-inbox email or physical-phone test claim.
