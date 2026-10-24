# Create an agent directly from selected conversation inputs

In general Work, select data files/documents or reviewed public sources, then ask
explicitly to create an agent. Preserve the selected scope in the existing queued
Agent Factory rather than executing a preliminary data analysis. Chat must request
switching to Work; quoted/negated creation text remains an ordinary analysis.

Use existing MessageBody.data and the frozen controller-owned selected_data_agent
metadata on user/parent/draft Runs. No new request field or schema is necessary.
Freeze inspected CSV/XLSX/JSON inputs and selected document metadata, their hashes,
original task, local analysis model, reviewed public query/URLs/rendering settings,
repair allowance and runtime budget. The model proposes identity, task wording and
schedule only; it cannot choose files/URLs/tools/project/email or permissions.

Drafting reads no public sources, executes no Python and creates no workspace.
Only manage_agents and, for selected stored files, scoped filesystem_read are
needed for validation. Verify current message/parent/Task authority, source state,
canonical source bytes and exact snapshot before/after inference and under the
publication Task lock. Source loss is not a JSON-format correction. Existing Stop,
leases, recovery, receipt replay and atomic disabled-definition/artifact publication
remain. Future activation and execution use normal agent permissions/workspaces.

Show selected request provenance inline and a concise Files & data hint. Preserve
one-off analysis and analysis-result actions. Clearing an old project selection
must actually allow general Work; a retained empty context row is not a project.
Test natural English/Polish and explicit action, Chat/mixed/external/quoted scopes,
input/document/public metadata and byte tamper, Stop, source change during inference,
restricted proposal correction, replay, no premature jobs, and future execution in
an owned workspace. Full local gates, image/Compose and compiled desktop/mobile
first-send flows are required before deployment. Distinguish injected and actual
local inference/native execution. Preserve current live #414 and root Memory WIP.

## Implemented increment and qualification

PR #415, branch `feat/selected-input-agent-draft`, is based on #414 (`fca17fb`).
The implementation uses the existing local factory and shared settings mapper.
It also accepts an explicit agent.create action with plain task instructions.
The model proposes task wording, so review that goal before enabling the draft.

Focused data/analysis-agent checks passed (59 initial cases, then 31 final selected
scope cases including parent Task/instruction tamper). Frontend formatting/lint/
typecheck/production build and 757 tests pass. Compiled 1440/390 cases exercise
first Work send with PDF or 180,025-character text plus reviewed public data,
explicit review/enable, two actual scheduler executions per case at forced due
instants, four actual native offline Python jobs, complete text and fresh captures
in separate worktrees. Drafting performs no analysis, reads or workspace creation.
Those browser cases inject inference, catalog and public responses.

A separate actual already-ready llama.cpp inference accepts a Polish daily 09:00
request, derives the correct summation task and Europe/Warsaw cron, and retains the
exact selected synthetic CSV/local data model in a disabled definition. It creates
no preliminary analysis/Python/workspace and preserves the actual model container
and 46,080-token preset. This is real drafting, not a real full-model data workflow.

The review tightened both source-bound factory paths: child instructions and Task/
conversation ownership must match the authorized current turn. Earlier complete
checks are retained under `before-origin-binding`; final complete CPU/image/browser
and real drafting checks use `0c8b1d9` or an application-identical documentation head.
Consult `data/acceptance/selected-input-agent-draft-20261024` and its post-deployment
qualification before treating #415 as live. Full-platform completion is still open.
