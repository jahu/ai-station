# MVP acceptance status

Updated 2026-09-25. This is an acceptance ledger, not a claim that the complete MVP is ready.

| Capability | Current evidence | Remaining acceptance work |
| --- | --- | --- |
| Startup | Native private runner + Docker API/worker/scheduler, health checks, owned shutdown; isolated fake smoke | Final clean-start check after remaining slices |
| Dashboard/system | Real two-GPU telemetry and native diagnostics; history charts | Agents/schedules/conversation activity integration |
| Images/library | Generate, edit, recompose, upscale; uploads, artifacts, live logs, cancellation, retry; fake pipeline integration | Opt-in real Qwen/Juggernaut/edit/recompose/upscale runs |
| Chat | Durable local compatible-provider streaming, stop/regenerate, restart; fake streaming/browser tests; real local qwen3:8b completion and persisted response | Rolling summaries/attachments |
| Runs | Durable lifecycle, events/SSE, worker leases/recovery, managed cancellation | Remaining filters and coding/agent result integration |
| Projects | Host-validated registry, policies, trusted command configuration, Git status | Actual coding execution and review |
| Worktrees | Worker-driven, runner-owned reservations, managed Git process, report artifact; disposable real Git tests | Agent edits, validation, diff review, self-development acceptance |
| Coding | Preserved inactive drafts; installed Codex/Cursor help inspected | Enforced sandbox, typed authorization, actual adapters, validation, diff UI, opt-in real tasks |
| Agents | Disabled draft factory, explicit activation, local executor, scoped tools, persistent schedules, history/UI; fake-provider coverage | Final acceptance with the remaining dashboard/runtime slices |
| Memory | Memory CRUD/FTS workspace, provenance, optimistic edits, scoped pinned Chat context | Rolling summaries |
| Models/runtimes | Managed metadata-only discovery Run, persistent file registry, Models UI and read-only diagnostics | Runtime instance registry (real metadata-only scan found 18 model files) |

Host coding sandbox probe: `bwrap --ro-bind / / --dev /dev --proc /proc --unshare-pid --die-with-parent -- /usr/bin/true` failed with `setting up uid map: Permission denied`. No OS setting was changed. The adapter must not bypass isolation to conceal this limitation. Installed CLI help alone does not prove sandbox enforcement or a successful coding task.

Real local compatible-provider completion was verified; real image/GPU generation and coding executor acceptance are pending. Normal tests use fake providers and temporary repositories. Protected release branches, existing runtime processes, original photo pipeline, models, drivers and CUDA remain outside this implementation's mutation scope.
