# MVP acceptance status

Updated 2026-09-29. The first local MVP is available with the tested scope and limits in the [acceptance report](mvp-acceptance.md); this is not completion of the full product vision.

| Capability | Current evidence | Remaining acceptance work |
| --- | --- | --- |
| Startup | Native private runner + Docker API/worker/scheduler, health checks, owned shutdown; isolated fake smoke | Fresh final Docker startup/restart/shutdown and fake-executor smoke passed |
| Dashboard/system | Real two-GPU telemetry and native diagnostics; history charts; bounded active Runs, agents, schedules, conversations, artifacts and aged runtime observations | Final Docker/browser acceptance passed |
| Images/library | Generate, edit, recompose, upscale; uploads, artifacts, live logs, cancellation, retry; fake pipeline integration | All six real GPU mode/backend cases passed at smoke-test sizes; broader quality/performance evaluation remains |
| Chat | Durable local compatible-provider streaming, stop/regenerate, restart; fake streaming/browser tests; real local qwen3:8b completion and persisted response; Docker → private runner bridge → loopback-only Ollama verified | Text attachments completed with provider/browser coverage; vision/PDF attachments and automatic summary scheduling remain future scope |
| Runs | Durable lifecycle, events/SSE, worker leases/recovery, managed cancellation | Combined filters/paging and Cursor review/validation integration completed |
| Projects | Host-validated registry, policies, trusted command configuration, Git status | Bounded Cursor and real AI Station self-development acceptance passed |
| Worktrees | Worker-driven, runner-owned reservations, managed Git process, report artifact; disposable real Git tests | Saved multi-command validation, Cursor edits, diff review and self-development passed |
| Coding | Real Cursor selected-file proposal → checked worktree writes → diff review → sandbox validation passed through Chromium; explicit external permission and managed cancellation | Real documentation-only self-development passed; Codex unavailable; unrestricted repository exploration and automatic Git publication remain outside this adapter |
| Agents | Disabled draft factory, explicit activation, local executor, scoped tools, persistent schedules, history/UI; fake-provider coverage | Real Docker → local Ollama agent report with scoped fixture memory passed; final clean-start acceptance passed |
| Memory | Memory CRUD/FTS workspace, provenance, optimistic edits, scoped pinned Chat context; explicit incremental summaries with immutable coverage and editable memory | Optional automatic summary scheduling |
| Models/runtimes | Managed metadata-only discovery Run, persistent file registry, Models UI, external runtime registry and read-only diagnostics | Read-only runtime instance registry and real Ollama process observation completed; managed llama.cpp multi-GPU load, inference, stop and reload are verified |

Host coding sandbox probe: `bwrap --ro-bind / / --dev /dev --proc /proc --unshare-pid --die-with-parent -- /usr/bin/true` failed with `setting up uid map: Permission denied`. No OS setting was changed. The adapter must not bypass isolation to conceal this limitation. Installed CLI help alone does not prove sandbox enforcement or a successful coding task.

Real local compatible-provider completion was verified; all six real image/GPU scenarios passed small acceptance Runs. The bounded Cursor executor passed a real disposable-repository acceptance task. A real documentation-only self-development task passed with both syntax checks, unchanged original checkout/index and preserved review artifacts. Normal tests use fake providers and temporary repositories. Protected release branches, existing runtime processes, original photo pipeline, models, drivers and CUDA remain outside this implementation's mutation scope.


## Implemented since the initial acceptance

- Managed llama.cpp: model selection, multi-GPU load/stop and saved-preset reload; real 9B and 27B Q4 chat verified.
- Audio and avatars: real local Chatterbox WAV generation and EchoMimic portrait-plus-audio video. General text-to-video and music remain future work.
- Library: import, search, filters, titles/notes, reversible trash and restore. Assistant can select Library media or reuse prior outputs with ordered image references.
- Chat: unified searchable model picker in settings and conversation header.
- Coding: reviewed task-branch commits; Local AI selected-file proposals now share Cursor's checked worktree/diff/validation workflow. Real 27B Q4 proposal smoke passed; automated coverage includes cancellation and validation/commit. Codex/Claude and autonomous whole-repository exploration remain unfinished.

The central Assistant supports explicit capability routing, local/consented Cursor coding and media results; a general multi-step tool-using orchestrator, external connectors, cloud-provider Chat and multi-node execution are still incomplete. The initial MVP acceptance above must not be read as 100% of the full product specification.

- Optional Chat web search: explicit switch and editable public query, private SearXNG, persisted source cards/events/artifact, cancellation and visible failure. Real browser → search → local 27B response passed. General page browsing and agent web tooling remain separate future work.
