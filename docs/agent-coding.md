# Local coding agents

Choose **Local coding** in an agent definition, select a Project and a local model, describe the coding goal and save. Select this tool alone; report/search tools remain separate workflows. Enabling the reviewed definition is explicit. Manual, interval, cron and datetime triggers reuse the durable agent scheduler. Gated mode or Require approval parks the workflow before any worktree is prepared.

Every execution publishes the existing Local Coding workflow: fresh owned Git worktree and task branch, bounded repository exploration, local proposal, diff/JSON artifacts and configured project validation commands. It never edits the original checkout or commits/pushes/publishes. The agent's instructions and verified Skills join project guidance without granting extra tools. Other active project work blocks dispatch.

The agent history shows the entire child chain and links to **Open coding task** for review and continued prompts. Cancellation reaches the current owned descendant; uncertain native completion follows existing inspection/recovery rules and is never blindly replayed. Manual retry creates a new reviewed workflow/worktree. Success notices distinguish results ready for review from publication, and configured validation must succeed before a success notice.

Maximum runtime starts when an approved workflow publishes its coding work. Its immutable deadline follows preparation, proposal and validation. The worker checks it before dispatch and its independent heartbeat requests owned-run cancellation when it expires (normally within five seconds plus cancellation grace). Shared model loading is not killed by this deadline. Human follow-up prompts and manual repairs start fresh work without inheriting the previous autonomous deadline.

No schema change is needed: the selected Tool and project already belong to Agent definitions, and ordinary Runs preserve snapshot instructions, permissions, model and deadline. No arbitrary shell, external AI or generated validation command is authorized.

## Real acceptance — 2026-10-13

An opted-in isolated control-plane database and private native Runner loaded the existing local Qwen3.5 9B with Q8 cache and 131072 context. A name-only managed project and explicitly enabled coding agent then ran ordinary workflow → worktree → Local Coding → validation Runs. The model created `src/calculator.py` and unittest cases; configured unittest discovery in `src` passed. A success notice persisted and the original project checkout status stayed unchanged. No commit, publication, external AI or model download occurred; the test-owned runtime and Runner were stopped.

The first attempt is retained as failed validation: its configured command searched the repository root while generated tests were under `src`, so no tests were discovered. The corrected repeat explicitly bound the goal and trusted command to `src`; the unsuccessful result was not relabeled. Evidence: local `data/acceptance/agent-coding-20261013/`. This confirms a basic real agent coding task, not correctness on arbitrary projects.
