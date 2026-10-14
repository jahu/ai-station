# Conversation-first AI Station: implementation brief for GPT-6.1-Sol

Status: **planned, not implemented**. Decision date: 2026-10-14.
Owner request: a ChatGPT/Claude-like entry experience, visible Chat/Work modes,
model and supported reasoning controls, distinct System and Settings, and useful
longer local video/avatar output on the existing workstation. Retain all dedicated
workspaces. This brief defines product behavior; it is not a claim of parity with
either named product or of completed hardware acceptance.

## Start here

1. Read this brief, then [conversation UX and contracts](chat-work-experience.md).
2. Implement [System/Settings separation](system-settings-separation.md) alongside
   the conversation milestones, without replacing the working execution engine.
3. Follow [long media execution](long-media-execution.md) for media. It includes
   the measured baseline, algorithms, resource policy and hardware gates.
4. Read the handoff below before touching either existing unfinished branch.

These plans supersede the old requirement to click **Create conversation** before
typing and the old assumption that all media tools require Platform assistant.
They do not supersede security, Git, approval, ownership or recovery contracts.

## Product decisions

| Area | Decision |
| --- | --- |
| Entry | `/` immediately presents an editable composer. First Send creates the conversation and queues the turn atomically. No setup wizard, title form or endpoint field on the happy path. |
| Modes | Two visible choices: **Chat** and **Work**. Chat includes explicitly requested media and opt-in web search. Work adds project changes, coding and persistent agent management. A mode selects an allowed action set; it never grants all permissions. |
| Default | First visit uses Chat with an available local model. Remember the last explicitly selected mode/model for new conversations. Existing conversations retain their saved behavior; do not migrate Work conversations into Chat. |
| Model | One searchable picker showing local llama.cpp files, configured local servers and explicitly configured external models. Auto stays local unless the user explicitly selects an external provider. GPU and context details move to an optional inspector. |
| Reasoning | Show controls only for a verified model/runtime combination. Native effort, a thinking toggle and a thinking-token budget are distinct capabilities. Unsupported controls are absent, not decorative. |
| Conversation | One transcript for text, ordered attachments, sources, progress, approvals, code review and playable artifacts. Continue without navigating to Runs or recreating the task. |
| Navigation | Preserve Home, Chat, Images, Video, Audio, Avatars, Coding, Projects, Agents, Models, Library, Runs, Memory, System and Settings. Keep Coding session history. Make conversation history collapsible so it does not create a permanent second sidebar. |
| System | Observed workstation state, processes, runtime observations, execution health and diagnostics. |
| Settings | Preferences, providers, connectors, operator access and maintenance configuration/actions. Real settings only. |
| Long video | Generate real motion in bounded segments; compose a final MP4 with durable progress and resumable completed work. Offer continuous-scene and multi-shot forms with honest continuity semantics. |
| Long avatar | Animate the full selected recording/generated speech. Preserve audio timing and identity across windows, rather than truncating to the opening three seconds. |
| Two GPUs | Use dynamically discovered devices. Parallel independent shots only when both VRAM and system RAM admission pass. Continuous dependencies stay sequential. Two 12 GiB devices are not a transparent 24 GiB allocation. |

## What was actually inspected

Baseline is `origin/develop` **806b604** (PR #267), also the deployed UI at
`http://127.0.0.1:8765/`. Open PR list was empty. Read-only Chromium inspection
covered entry, Settings, Video and Avatars at 1440×1000; no forms were submitted.
Current entry indeed displays a model/settings form instead of a message input.
`frontend/src/App.tsx` renders `System` at both `/system` and `/settings`.

The selected local configuration references existing ComfyUI/Wan and EchoMimic
installations. Read-only `nvidia-smi` reported two RTX 3060 devices, each 12288 MiB;
system RAM was about 32 GiB. Those are this inspection's observations, not app
constants or a proof that two concurrent video processes fit RAM.

No inference, model load, installation, benchmark, service restart or deployment
was performed for this planning change. Prior real-media evidence is linked in
the media plan and must not be relabelled as new long-media acceptance.

## Delivery order and reviewable increments

Each row is a feature/fix PR to `develop`, with a usable end-to-end result. Keep
schema, contract and UI changes together where splitting would publish a broken
flow. A row may be split only when both halves remain independently usable.

| Order | Deliverable | Depends on | Required acceptance before closing |
| --- | --- | --- | --- |
| 1 | Atomic first-turn API, explicit Chat/Work policy and versioned conversation defaults; reuse the current composer for an immediately usable entry | Existing chat/assistant services | First prompt without Create conversation; duplicate/retried POST produces one conversation/turn; Chat cannot execute Work mutations; existing URLs/history still work |
| 2 | Finished conversation shell, compact model picker, attachments, result cards, follow-up scope and accessible history | 1 | Desktop/mobile browser scenarios C1–C9; media available in Chat; no manual runtime load on the happy path; explicit cloud selection retained |
| 3 | Dedicated Settings and focused System | Existing components; no dependency on long media | All old maintenance links resolve; each setting exists in one canonical page; System shows real telemetry and no provider/password forms |
| 4 | Verified reasoning controls through provider, private bridge and owned llama.cpp | 1–2 | Wire payload tests plus opt-in local on/off or effort acceptance; unsupported combinations omit the control; Coding JSON output remains valid |
| 5 | Work context continuity and reviewed completion of the existing create-project-and-code WIP | 1–2; inspect WIP below | Name + goal → project → worktree → proposal → checks, then a follow-up on the same task/worktree; no cloud/commit/publication grant inferred from text |
| 6 | Media capability profiles, immutable duration plan, dependency graph, CPU composition, task Stop/resume and resource admission | Existing RunDependency and owned media lifecycle | Fake segmented execution and real disposable CPU media tests; deterministic duration, cancellation/recovery/race tests; no fake long-GPU success |
| 7 | Longer Wan scene/shot generation and duration UI in Video + conversation | 6 | Real ≥15 s continuous sample and ≥30 s multi-shot result; full decode, join quality, refresh and Stop; old short-clip paths retained |
| 8 | Full-speech EchoMimic avatars, typed-speech integration and audio-aligned composition | 6; compatibility gate in media plan | Real 30 s and 60 s speech coverage, audible final words, frame-accurate timing and inspected joins; 120 s capability only after its own acceptance |
| 9 | Qualified two-GPU shot scheduling and final UX/reliability acceptance | 7–8; RAM admission already exists in 6 | Concurrent independent work on both devices only when measured fit passes; sequential fallback works; mixed Chat/media load remains responsive |

Do not delay the new entry experience behind video research. Do not declare this
initiative finished after the new UI alone. Finish 1–9, recording actual results
and remaining hardware-specific cases. This is the next product milestone; the
broader product ledger remains the authority for unrelated unfinished capabilities.

## Definition of done and efficient validation

- UX: real browser checks at 1440, 1024 and 390 px, 200% zoom, keyboard-only use,
  loading/failure/empty states, no horizontal page overflow, no console errors.
  Preserve the dark visual language; no wall of configuration or developer notes.
- Execution: selected mode/model/settings/inputs persisted per turn; side effects
  use ordinary Tasks/Runs; Stop and refresh work through child transitions.
- Media: final duration, audio, resolution and continuity checked on decoded
  outputs, not inferred from requested parameters or exit code alone.
- Regression: existing conversations, coding worktrees, artifacts, links, agent
  schedules, approvals and provenance survive migrations and deployment.
- Run focused tests while editing, then repository-required checks once on the
  reviewed final head. Backend/runner: `./scripts/check.sh`. UI: format, lint,
  typecheck, tests and production build. Deployment changes also require both
  Compose configurations and Docker build. `./scripts/check-all.sh` is the combined
  path; do not repeatedly rebuild unchanged images during research.
- Normal tests use fake providers and temporary storage. Real GPU/provider checks
  are explicit opt-ins, bounded, and recorded separately. No unattended downloads
  or external-token consumption. Keep a small acceptance matrix, not dozens of
  identical screenshots or repeated unchanged suites.
- Review the complete PR diff, use successful local verification as authorized
  while hosted Actions credits are exhausted, squash to `develop`. Never bypass
  actual failed checks. AI Station restart permission already exists; back up data
  and deploy the reviewed release when implementing, not during planning.

## Handoff: preserve existing work

The planning branch is `docs/chat-work-long-media`, in
`.tools/plan-chat-work-media`, based on **806b604**. It contains documentation only.
The active implementation goal was paused before this planning request; this
request authorizes analysis/documentation, not resuming implementation.

Two separate unfinished workstreams exist:

1. Root checkout `feat/memory-scope-tagged-runs` at **6ba096d** has modified README,
   architecture, Memory/status docs and `Memory.tsx`/test, plus `docs/handoff.md`.
   Preserve all of it. Do not overwrite, stage with this work, reset or stash it
   as a shortcut. Root docs are not the current deployed implementation snapshot.
2. `.tools/assistant-project-build`, branch `feat/assistant-project-build`, based
   on **806b604**, has uncommitted backend/frontend/test/docs changes. Its
   `project_build.py` composes existing project setup → worktree → coding on one
   Task, with Local AI by default and explicit external consent. It is **not
   merged or deployed**. Reuse/review it in increment 5; do not rewrite it merely
   to fit new component names. Its explicit `NewProjectBuild` form becomes a
   contextual Work card rather than a mandatory entry screen.

The previous implementation handoff reported 19 targeted backend tests passing
for that WIP, but full checks/review/PR/deployment remain pending, and the latest
targeted UI result was not confirmed. Inspect the worktree and test results anew;
do not count unverified tests as passed. This planning work does not finish it.

The running release is `.tools/ui-coding-removal-20261014`; data is under
`data/preview`. Existing deployment evidence is
`data/acceptance/coding-removal-20261014`, with central deployment metadata in
`data/acceptance/safety-redeploy-20261012/deployment.json`. Revalidate the actual
release/process state before any future rollout. Do not restart unrelated services.

For the next model: inspect current status/PRs, read this plan, then start increment
1 in a clean feature worktree from the updated `develop`. The user will explicitly
switch model/resume implementation. Do not run the implementation backlog in the
planning turn. Do not repeatedly re-audit completed unrelated features.

Use `PYTHONPATH=backend:host-runner` when running Python checks in a new worktree;
the shared editable virtual environment otherwise imports the older root checkout.
Use `scripts/frontend.sh` for the repository's Docker-backed Node tooling. Do not
assume host Node is installed or run tests against the deployed database.

Planning validation: reviewed against the baseline implementation and installed
adapter sources, inspected the live UI read-only, checked all changed Markdown
links/anchors and `git diff --check`. Application suites, image builds and GPU
smokes are intentionally not rerun for this documentation-only change; the
implementation increments above each specify their required tests.
