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
