# CSV and Excel analysis in the conversation

Active implementation, 2026-10-23. Persistent data agents and the actual offline
Python executor already work; reuse them. The current main Chat cannot request
that execution directly. Adding a persistent Agent must remain optional.

## One Send contract

A selected CSV/XLSX scope and current question authorize bounded local analysis
in Chat or Work. Upload/Library selection uses the existing stored-input and
queued inspection APIs. Show file inspection progress and keep Send disabled
until every chosen file is inspected. Original files remain read-only. A fitting
local model is chosen automatically, with an optional installed llama.cpp model
override. The tool clearly discloses local execution even if ordinary conversation
uses an external provider; data and previews are not sent to that provider.

Use a typed optional request scope: one to eight Artifact UUIDs, zero to two
repairs, Auto/installed local model and a bounded runtime budget. Native paths,
commands, interpreters, projects, credentials and arbitrary tools are absent.
A current explicit data scope is required; a model plan/history/source cannot
choose files or start Python. Reject mixed media, text attachments, project/Git,
runtime, account and exact Web scopes. Ordinary default Web is turned off for
this data operation. Preserve old receipt shapes when no data scope exists.

## Shared execution and ownership

The existing orchestrator publishes ordinary project setup on its Task. Project
setup provisions a private owned workspace using the existing native factory.
Its completion publishes the existing workflow/worktree → local script generation
→ offline Python → validated data-result graph. No persistent Agent row, agent
activation, new executor, native API or second Python runtime is introduced.

Existing pure definition/file/repair settings can configure the reused pipeline;
they do not grant a persistent agent identity. The new conversation origin binds
the actual root Run, user message, conversation, Task, setup receipt, private
Project, exact frozen inputs, fixed permissions and absolute deadline. Validate
that binding before native setup, after adoption and before every generation,
dispatch/result/repair stage. A missing origin on an agent-less data workflow
fails closed. Existing persistent-agent validation remains unchanged.

Model output cannot replace input IDs, workspace, model routing, tool scope,
retry count or deadline. All stages use normal leases, model admission, hashes,
owned-container inspection and Task-wide Stop. Uncertain cleanup/interruption
never reruns Python. Correct only confirmed program/result-contract failures
within the original budget. Workspace and prior attempt scripts stay available
for inspection; there is no destructive automatic cleanup.

## Results and UX

Reuse the existing data-file and data-result components: answer, bounded table,
Download CSV, Python source and execution links. Inline Task status accounts for
only explicitly validated repairs, without showing an early program failure as
final success or masking unrelated errors. Reload restores the result and source
links. Show the actual local model. Keep manual repositories/branches/configuration
out of the normal upload → question → answer path. Preserve existing workspaces,
text/PDF/media inputs and persistent data agents.

## Gates

Temporary DB/fake inference and actual disposable offline CPU execution cover
Chat/Work first Send, normal follow-up, inspected input selection, private project
ownership, local model constraints, receipt replay, old body compatibility,
foreign/missing/changed origin, source bytes/hashes/trash, non-expanding permissions,
shared expiry, one repair, missing/bad outputs, Stop during setup/model/Python,
conservative recovery and final provenance. Add compiled desktop/phone upload,
inspection, Send, table/download/reload and Stop acceptance. Pass normal full
checks, frontend gates, Docker/Compose, review and PR to develop before rollout.
Then qualify one short actual local-model conversation using synthetic full-file
CSV/XLSX data and preserve the operator's original model preset. No new model or
Python package download is implied.
