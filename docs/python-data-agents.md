# Local Python data agents

Implementation contract: persistent `python_data` agents select stored, successfully
inspected CSV/XLSX artifacts and a local model. Their activated definition includes
input UUIDs and a bounded repair count. Capability activation requires an installed,
configured offline Python image. No external provider or package install is implied.

The existing agent workflow provisions its private project when necessary and
creates a fresh owned worktree. A local generation Run receives only bounded,
untrusted previews and the reviewed goal; it returns a JSON object containing one
Python script. The platform validates syntax and length, records the source and
passes the artifact to the typed Python dispatch. The Runner snapshots that exact
source and creates a new `analysis-<run-id>.py` in the owned worktree without
overwriting previous attempts or user files. Draft filesystem writes stay disabled.
Actual inputs remain read-only; model output cannot choose host paths or tools.

The existing Python executor freezes that script hash and reviewed inputs and
executes in its offline CPU container. Mandatory `result.json` and `result.csv`
outputs are bounded and verified before a result stage validates the answer/table,
records provenance and presents download links. A successful process alone cannot
claim a valid answer. Formula-bearing spreadsheet cells are not evaluated; generated
CSV export must remain literal data when opened in a spreadsheet.

All stages share the original runtime deadline, Task Stop, agent identity and frozen
input scope. Repairs apply only after confirmed program/contract failure within the
saved attempt/time budget; interruption, uncertain cleanup or lost process ownership
never trigger replay. Each script attempt and output is an inspectable artifact.
Model requests remain local; a fitting managed model with 100k+ actual context is
required for production code generation. Normal tests use fake local inference.

Acceptance: persistent selection/edit/activation and schedules; automatic workspace;
CSV and genuine XLSX tasks; correct generated answer/table/download with original
hashes unchanged; one bounded repair; failed/missing/invalid outputs; scope changes;
Stop during model and Python stages; stale-lease inspection without replay; provenance
and desktop/mobile result UX. Fake-provider and real local-model qualification are
reported separately. This document does not assert completion of that acceptance.
