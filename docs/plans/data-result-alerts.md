# Conditional data-result notifications

Extend the existing reviewed report criterion to persistent Python/data agents.
Keep verified data generation/results separate from notification classification:
after adopting the complete checked JSON/CSV/exports, publish one ordinary
`agent_result_alert` child Run bound to that exact successful result. A failed,
canceled or interrupted check retains the data result and never triggers Python
repair/re-execution. Existing report agents retain their working inline check.

Reuse the selected generation model, local provider, managed-model preparation,
original shared deadline, strict tools-free decision and current notice/email
services. The check receives only filesystem/network-read authority needed for
verified report bytes and local inference; no code, memory-write or mail authority.
Binding/preparation errors belong to the check, not the completed analysis.
Task Stop/leases/recovery remain ordinary Run contracts; never blindly replay.

Read the exact DataAnswer JSON and bounded table preview through the existing
verified-result reader. Freeze/reverify its Python-result ownership, source hashes
and workflow definition before comparison/publication/transport. Compare only the
same agent and reviewed definition, normalizing solely the existing verified
controller-created private-workspace derivation. Do not reopen original uploads,
read arbitrary worktrees or claim to inspect omitted table rows. A changed/missing
baseline fails closed. Decision stage, reason, baseline and source remain visible.
Only a successfully checked result advances the comparison baseline: a failed or
canceled check must not swallow a finding on the next execution. Reusing a checked
result verifies its own report/authority, without requiring every earlier report
in its historical comparison chain to remain available.

Keep generation outcome distinct from notification-check and SMTP outcome. Both
success notices and configured email wait for a successful matching check; false
decisions retain the result/memory without sending. Publication is idempotent per
source; direct publication/transport cannot bypass the check. Empty defaults and
old report decisions retain identity. Recognize `report_condition` in legacy-policy
coercion so a criterion-only request is preserved instead of silently discarded.
Code/media/market criteria remain explicitly unsupported.

Enable the same field in data-agent settings/review and show the actual check in
data result workspaces. Preserve criteria during unrelated edits. Qualify normal
worker publication, matching/suppression, private-workspace continuity, bad sources,
classifier/preparation failures, Stop, lease recovery and SMTP gates using fixtures.
Run complete local gates, compiled desktop/mobile flows and bounded actual CPU/
local-model acceptance with explicit provenance for any injected code generation.
Review and squash a PR to develop, then qualify a data/auth/native/model/private-
service-preserving controller rollout. Full-platform completion remains open.


## Implementation and verification

PR #432 implements the shared reviewed field, durable check, source/model/budget
binding, comparison baseline and independent result/notification outcomes.
Conversation execution receipts also expose the actual alert-check state and
inspection link, including when model preparation was required.

Local qualification: all 3855 baseline CPU cases (3846 pass, nine expensive opt-in
skips), final 54 outcome/data cases including three added inspection-link
regressions, Ruff/format, and the full 806-test UI suite with format/lint/types/build.
The final normal collection has 3858 cases: baseline nodes are preserved, only
three cases were added, and the sole production delta after the full CPU baseline
is the verified outcome-link correction. No failing check is waived.

The exact Docker image, normal/dev/private-LAN Compose and isolated-image fake
API/worker/SQL/SSE/reopen pass. Compiled desktop/mobile settings save/reload/enable
and four actual worker workflows retain analysis and match/suppress notifications;
code generation and Python responses in those flows are injected. Two actual
local-model classifier cases correctly match a first total27 and suppress the
same total next time, preserving the ready container and 46080-token preset.
Their upstream generation/Python graph and selected-model binding are explicit
fixtures; this does not claim new real long-context code generation or GPU Python.
Earlier real native Python and long-context qualifications remain separate.

Evidence: `data/acceptance/data-result-alerts-20261025`. Initial harness failures,
corrected UI text assertions and the actual red/green outcome-link regression are
retained. `post-deployment-qualified.json` and the shared deployment authority
prove merge/rollout status; local qualification alone is not a deployment claim.
Native Runner, schema, dependencies and external runtimes are unchanged.
Whole-platform completion remains open.
