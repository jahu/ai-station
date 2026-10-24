> Current delivery: #408 is live and qualified. Agents can email explicitly
> selected generated CSV/XLSX/PNG/text exports, with exact-source receipt and
> private TLS SMTP qualification. Evidence:
> `data/acceptance/agent-data-email-attachments-20261024/post-deployment-qualified.json`.
> Active feature: [saved HTTP/API sources](agent-http-connectors.md), migration
> 0034 and both agent editors. This feature is not deployed until its gates and
> release verification pass. Preserve the root checkout's unrelated Memory WIP.

# AI Station implementation handoff

The full platform goal remains active. Prioritize useful local agents and
conversation-first workflows; standalone IDE/external coding expansion is deferred.
No subagents, unapproved model downloads, driver changes, public exposure or
main/master operations. Preserve existing services, records and original root WIP.

## Authoritative live state — 2026-10-24

PR #406 merged to develop as `ee07d34827d3e11ca2ef4c417862f85521b4c89b`, reviewed
source `4b458a2968b864b8603177df70dce2ba413fa50c`. Live controller release:
`.tools/ui-file-creation-conversation-context-20261024`.
LAN UI: http://192.168.1.121:8765. Deployment/image/backup authority:
`data/acceptance/safety-redeploy-20261012/deployment.json`.
Latest qualification:
`data/acceptance/file-creation-conversation-context-20261024/post-deployment-qualified.json`.

Delivered: instruction-only CSV/Excel/PNG/text creation in Chat/Work and persistent
Python agents, explicit Files & data controls, natural clear requests, verified
created-workbook/CSV reuse, and bounded earlier plain conversation text. The
collapsed context note shows exactly which text was supplied. Source IDs/hashes
and matching current-message/Run snapshots gate execution. No attachment reads,
URL fetches or additional permissions are inherited from earlier text.

Actual normal-worker local inference at 131072 context created independently
checked rows 4/16, 7/49, 11/121 using the earlier conversation values and the current
instruction's heading override. One bounded Python correction was needed; failure
history is retained. CSV/XLSX/PNG checks pass, original model/GPU/cache/context was
restored, QA conversation archived and no persistent Agent created. Native Runner
PID/fingerprint/socket and operator auth/IDs/agent definitions/due instants remain
preserved; query actual live state before the next rollout. Schema remains 0033.

Full #406 gate: 3298 Python/Runner cases (3289 passes/nine opt-in skips), Ruff,
727 UI tests, format/lint/types/build, exact image/backend/assets, three Compose
configurations, compiled 1440/390 single-click context inspection, downloads,
explicit/natural reuse, reload and Stop. Actual CPU context/replayed-code check
also verifies all ten sample CSV/XLSX rows, PNG, bounded intentional repair and
workbook follow-up total 55. This injected-inference check is separate from the
actual production local-model qualification above.

The first compiled click exposed an existing 23px timestamp focus shift. The
corrected layout passes actual first-click opening at both viewport widths.
A later rejected coordinate assertion confused expected scroll/expansion with
focus movement; retained evidence explains the corrected behavioral assertion.
No physical-phone test or operator-inbox email delivery is claimed.

PR #405 (`7ea7da9`, reviewed `6748bf3`) corrected redundant mandatory CSV/JSON
names in model manifests without widening the native export allowlist or adding
model calls. Its actual ten-row local-model example passed in one Python attempt:
`data/acceptance/data-output-declarations-20261024/post-deployment-qualified.json`.
The original #404 rejected production attempt remains under
`data/acceptance/local-file-creation-20261024`; do not relabel it or rerun it.
Merged remote #404/#405/#406 feature branches were removed after qualification.

## Current owned increment

Branch `feat/agent-data-email-attachments`, `.tools/agent-data-email-attachments`,
based on docs delivery #407. Read [data email attachments](agent-data-email-attachments.md).
The existing result email sends only body text/result IDs. Candidate adds explicitly
selected generated CSV/XLSX/PNG/text, required creation of those formats, exact
receipt/approval MIME manifests, actual file verification and clear settings,
activation consent and common delivery preview. Defaults preserve old identity;
no native, schema or dependency changes. No external mail is authorized for QA.

Initial105 existing mail cases and the complete new MIME path pass. New negative
cases cover changed/trash files, input-pointer substitution, symlink/hardlink,
missing permission, post-connect revocation, Stop and unknown-outcome non-replay.
One test incorrectly expected automatic email before two ordinary created-file
inspections; its drain is corrected. A nested separate-session Stop fixture hit
its own SQLite write lock; inject the committed cancellation in the worker session
for that last-check test. Public post-connect cancellation/authority tests remain
separate. Finish full gates, actual isolated native-CPU/TLS sink, compiled desktop/
phone settings/approval/receipt/reload/Stop, full review and develop deployment.
Live remains #406 until this increment's post-deployment-qualified report passes.

Keep the full platform goal active after delivery. Prioritize useful general-agent
tool composition, retaining the [product ledger](../product-completion.md) and
[agent-first direction](agent-first-product.md). Do not repeat prior qualified
media/model/research jobs. SMTP inbox/Tailscale enrollment requires operator
configuration and does not block independent implementation. Earlier evidence is
linked from the ledger and [historical handoff](implementation-handoff-history-20261024.md).

## Operations and preserved work

Root `feat/memory-scope-tagged-runs` at `6ba096d` retains original README,
architecture, Memory docs/UI/tests and handoff WIP. Do not edit/reset it; that
functionality was already ported in #319. Use owned worktrees and keep .venv/
node_modules links untracked. Node:
`.tools/node-runtimes/node-v22.23.3-linux-x64/bin`.
Read AGENTS.md and architecture/security/README. Complete local checks replace
manual hosted Actions under the user-approved account-credit exception; actual
failures are never waived. Full diff review and satisfactory checks precede squash
merge to develop. Controller restarts are authorized; preserve unchanged Runner
and model. Back up before rollout. Whisper-small consent remains pending; do not
infer a download approval. The full-platform objective is not complete.
