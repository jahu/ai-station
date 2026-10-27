# Explain resource waits in data results

The real CSV/GPU-pressure acceptance passed, but the analysis card showed
`running` / `Preparing data analysis` while its Task and model load were queued.
Existing conversation and agent projections already include the exact Run's
resource-wait observation; no backend, scheduler or execution change is needed.

Reuse the shared GPU/RAM notice for a queued Run in the current Task, with its
exact inspect link and truthful queued badge. Completed results and terminal or
stopping executions take precedence. Ignore other Tasks, mismatched Run IDs and
stale observations on nonqueued Runs. Once the model starts, remove the retry
notice and show the existing execution progress, naming model loading where
applicable. Preserve the current layout, source/download actions and Stop scope.

Qualify actual API-shaped analysis/agent graphs, state changes and completion/
cancellation guards. Run frontend format/lint/types/tests/build, inspect the
compiled desktop/mobile conversation against a real bounded VRAM wait, and
cancel that disposable queued analysis through its normal Task control. No new
expensive generation is needed to verify this presentation change.
