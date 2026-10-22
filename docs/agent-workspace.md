# Agent workspace

Agents own useful outcomes, including code and data execution. Their detail view
must show the latest outcome and progress before the saved configuration.

## Delivery contract

- Existing agents open Workspace with the latest data table or report, workflow
  progress and execution history. Inactive drafts without history open Settings.
- Workspace and Settings are linkable views on the same stable agent URL. Browser
  Back/Forward and reload preserve an explicitly selected view.
- Run now keeps the operator on the workspace, invalidates ordinary queries and
  reveals progress. It never changes activation, tools, model or saved scope.
- Settings keeps the existing versioned editor mounted, so unsaved changes survive
  view switches and polling. Switching views performs no write or inference.
- Status/actions stay compact and available in both views. Full permission and
  project metadata belongs beside configuration. Waiting approvals remain visible.
- Code results keep the existing task link for continuation and review. Do not
  remove Coding routes/navigation until equivalent embedded review, files and
  continuation are delivered. Isolated website preview remains a separate boundary.

Qualification: regression coverage for run-in-place, view persistence, unsaved
edits and draft defaults; existing editor/history/approval/Stop tests; full frontend
checks; actual desktop/mobile browser result/download/navigation acceptance with
no inference. This increment does not claim complete agent follow-up or website
preview delivery.

## Code workspace and follow-ups

Reuse the existing coding conversation component inside the agent's Workspace.
Resolve the latest Task from the agent's persisted Runs and open it only after a
proposal/preparation record proves it is a coding conversation. Show instructions,
local/external identity, results, changed files/validation/build artifacts and the
existing follow-up composer on the agent page. Do not infer a new project or task.

The original conversation remains available at its old URL and both views share
the same Task-keyed draft. The embedded view must not auto-scroll on mount or
background polling. Settings switches keep its editor and in-flight requests.
Follow-ups retain the existing expected-proposal guard, worktree, model, consent,
Task Stop and inherited Task/agent provenance. No execution API change is needed.
Existing approval gates remain before execution. Initial source-page fetches and
isolated website preview remain separate stages; this does not grant network or
publication permissions.
