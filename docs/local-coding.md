# Local coding proposals

The local coding adapter extends the existing bounded proposal workflow: Task → owned worktree preparation → local model proposal → checked file replacements → configured validation → review → optional reviewed commit. The model receives only selected UTF-8 source snapshots and project guidance, through the configured local inference endpoint or an owned llama.cpp instance. It has no tools or shell access.

The control plane snapshots the model and project configuration. Managed llama.cpp loading is a normal prerequisite Run; active coding consumers protect their model from idle eviction. Native request ownership, process-group cancellation and conservative interrupted-run recovery use the same contracts as Cursor. Model output must be one bounded JSON proposal for selected paths; malformed, truncated, tool-calling or failed responses never authorize writes. Worktree identity and input hashes are checked again after inference.

Local execution requires filesystem_read, workspace_write, git_read and network_read for the configured local inference bridge. It grants no external_ai permission, caller-selected URL, model installation or arbitrary command execution. Secrets remain in the Runner's configured provider; the coding subprocess communicates over its private Unix socket. A confirmed proposal produces the existing diff and JSON review artifacts and queues trusted project validation. Successful generation does not mean successful validation or approval.

Initial scope remains selected-file proposals, not autonomous whole-repository exploration. No automatic retry, push, merge or deployment is introduced. Cancellation/interruption preserves any partial worktree changes for inspection.

The first adapter uses a 2048-token response budget and a five-minute inference deadline. Choose a context size that accommodates the selected source text before first model load. Truncated output is rejected rather than partially applied. Normal integration tests use a fake UDS inference service and real disposable Git repositories; real local-model verification is explicitly opt-in.


Verification on 2026-09-29: real Qwen 27B Q4 inference through the existing two-GPU llama.cpp runtime changed a README in a disposable owned worktree and produced a review artifact. The source checkout and Git index were unchanged. This proves bounded local proposal execution, not autonomous repository exploration. Validation/commit, malformed and truncated replies, cancellation, request replay and saved-model reload use isolated integration tests with fake inference. The Assistant still routes coding through Cursor; Local AI is selected in the Coding workspace.

To repeat the real inference smoke using an already-ready owned runtime:

```bash
AI_STATION_REAL_LOCAL_LLM_TESTS=1 \
AI_STATION_SMOKE_RUNNER_SOCKET=/absolute/path/to/runner.sock \
AI_STATION_SMOKE_LLAMA_INSTANCE=<ready-instance-uuid> \
.venv/bin/pytest -q backend/tests/test_projects.py -k test_real_local_coding_proposal
```

The smoke does not load or stop models, modify registered projects, or create a production conversation. It forwards only the disposable test's source snapshot through the private Runner bridge.
