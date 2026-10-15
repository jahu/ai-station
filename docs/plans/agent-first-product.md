# Agent-first product direction

Decision: 2026-10-15, explicitly requested by the user. This supersedes earlier
priorities for a standalone IDE-like Coding workspace and large business-app
engineering. It changes the product acceptance target; it does not remove the
shared execution, Git, safety or observability architecture.

## Product contract

Chat remains the entry point, with Chat/Work modes and model selection. Agents
are durable definitions that can research, create files, write and execute local
code, remember observations, run on schedules and deliver results. Users describe
a result and inspect progress, outputs and history without configuring a software
repository, branches, validation commands or a coding CLI first.

Coding becomes an agent capability. AI Station will not prioritize competing with
Claude Code, Cursor or Codex as an environment for developing large applications.
llama.cpp remains a first-class local model runtime. A model runtime and an agent
execution environment have different responsibilities; existing permission and
execution boundaries still apply when the model writes code.

Stop expanding Cursor/Codex integrations, large-repository/IDE features, PR UX and
self-development acceptance as product milestones. Preserve working adapters,
records and routes for compatibility. Do not uninstall CLIs, remove user projects,
rewrite working execution code or delete coding sessions. Optional external
adapters are not required to complete the revised agent workflows.

## Existing implementation to reuse

- Persistent definitions, disabled factory drafts, explicit activation, schedules,
  approvals, retries, in-app notices, memory, selected tools and child Run graphs.
- [Local coding agents](../agent-coding.md): a real local task created Python code
  and tests in an owned worktree and passed its configured checks. This is already
  operational, not a capability that must be rebuilt.
- [Reviewed-page coding](../agent-page-coding.md): saved public URLs feed bounded,
  provenance-bearing context into that same local workflow. Its contracts have
  tests and real source-read/Stop acceptance; arbitrary website rebuilding is
  not yet qualified end to end.
- Managed project setup, worktrees, local model selection/loading, dependency
  installation, validation, diffs, builds and artifacts. PR #323 adds component
  environments and fixes real Python installer problems; it remains useful to
  agent code execution.

Current agent coding mainly produces a proposal and runs saved project checks.
It is not yet a general Python/data-analysis execution tool. Email delivery and a
qualified recurring market-alert workflow are also not operational acceptance.
Do not present these gaps as completed merely because HTTP/cron tools exist.

## Implementation order

### 1. Local agent execution and results

Introduce a typed local Python execution capability behind the Host Runner and
existing worker/Run infrastructure. An agent may write a script in its allocated
workspace, execute it, inspect bounded output and correct a failure within its
saved limits. Accept a validated relative script entrypoint and explicit input
artifact IDs; never accept a shell string, interpreter override or arbitrary host
path. Package preparation is a separate inspectable stage with constrained public
sources and a frozen manifest, preserving the existing dependency policy.

Use a controlled container target for generated Python: private PID namespace,
short private temporary storage, bounded CPU/RAM/processes/time/output, fixed
trusted runtime image, no networking by default, no GPU unless explicitly needed,
no Docker socket or host home/process mounts. Only the Runner invokes Docker.
Reuse existing owned-container reservation, identity, Stop and cleanup contracts.
The full self-development suite is no longer the reason to prioritize this
executor; safely running useful agent scripts is.

Reuse managed project setup internally to provision an agent workspace when
needed. Users must not manually register a repository to process a spreadsheet.
Retain versioned script/output artifacts, input hashes, source Run provenance,
structured execution events and reviewable diffs. Recurring executions use fresh
owned worktrees and an explicitly recorded script revision, not an unverified
leftover process or editable active checkout. Original files remain read-only;
modified data is a new artifact. A successful script exit alone does not prove
that the requested result or expected outputs exist.

First vertical slice: upload/select an XLSX or CSV, ask a question or request a
transformation, run local Python and show a table, answer and downloadable result.
Bound archive/file sizes, sheet/row/cell counts and parsing time; never execute
spreadsheet macros/formulas. Test malformed inputs, source isolation, repairs,
Stop, restart recovery and artifact provenance with synthetic data, then run a
real local end-to-end example. No external AI or real private spreadsheet is
required for acceptance.

### 2. Agent workspace UX and website-building acceptance

Make Agents and conversation results the normal place to inspect generated code,
execution logs, validations, files, preview, downloads and follow-up instructions.
Reuse the existing Coding services and inspector components underneath. Preserve
agent/task identity across follow-ups and show the actual selected model.

Remove Coding from primary navigation once those replacement views preserve
access to existing conversations/results. Retain old URLs or redirect them with
stable record identity. Move repository/branch/command/CLI controls into advanced
workspace settings; keep the dedicated Images, Video, Audio, Avatars, Models,
Library, Runs, Memory, System and Settings workspaces. Do not force users through
Git configuration for the agent happy path. Existing Projects remain available as
advanced reusable resources.

Qualify: create an agent from a public URL and a rebuilding instruction, approve
its source/network/workspace scope, fetch/render permitted source context, build
in its own workspace, validate and return a working isolated preview plus source
archive. Source pages are untrusted data, never instructions that widen tools or
permissions. Follow-up changes reuse the same conversation. Publishing or editing
the original website requires a separate explicit permission; a build is not a
deployment. First prove this with a disposable static site and the local model.

### 3. Recurring price alerts and real email

Add a real typed quote-data tool with configured provider, reviewed instruments,
quote timestamps, numeric values and source provenance. Use deterministic code
for thresholds and comparisons with the last valid saved observation. Stale or
missing quotes must not manufacture an alert. Distinguish schedule, observation,
comparison, notification and delivery as inspectable ordinary workflow Runs.

Add a real email connector with secret references, configuration/health state,
preview and a typed send operation. The reviewed agent definition scopes
recipients, instruments, change threshold, comparison window, schedule, cooldown
and email permission. Explicit activation may authorize unattended sends within
that scope; the model cannot add recipients or permissions. Keep credentials out
of prompts, reports and logs. Persist notification identity/deduplication and
confirmed delivery outcome; an uncertain send must not be blindly retried.

Qualify using deterministic quote fixtures and a local mail sink first, including
no-change, threshold crossing, duplicate suppression, restart, failure and Stop.
Then perform a specifically configured real read/delivery smoke when provider and
mail credentials are available. Do not claim real delivery from a fake connector.
No trading, account access, purchases or financial decisions are implied.

## Acceptance and scope accounting

The revised milestone is useful local agents with code execution and clear results:
spreadsheet processing, website generation with follow-ups, and scheduled
observation/conditional email. Existing chat/media/model/memory/operations goals
continue. Rich IDE features, parity with external coding products, external CLI
integration expansion and a full AI Station self-development workflow are outside
this milestone. Retain their working foundations and historical evidence.

For each enabled capability verify its definition/permissions, local runtime fit,
Task → Run → Events → Artifacts, limits, Stop, conservative recovery, history and
real output. Mark implemented, fixture-tested and real-tested separately. Rebase
future completion estimates on this explicit scope; do not obtain a claimed 100%
by silently counting old requirements as completed.

## Private access follow-up (2026-10-15)

The owner requested home LAN access and future worldwide mobile access through Tailscale with an operator password. Deliver explicit private UI publishing, independent device sessions, exact Host/Origin validation and password-required startup first; keep execution-node and model transports unchanged. Document optional Tailscale Serve over HTTPS, without installing a system service, opening router ports or enabling public Funnel. Resume the Python-capable agent workflow afterward; this does not restore IDE priorities.
