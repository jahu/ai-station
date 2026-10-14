# Chat/Work and longer media: current implementation handoff

Planning checkpoint: 2026-10-14, `develop` **f7387bf**. This document updates the
[delivery brief](2026-10-chat-work-media.md), not the execution architecture.
The original planning turn requested analysis/documentation only. **The user has
since explicitly resumed implementation and corrected an erroneous pause.** Do not
treat that historical planning-only instruction as a current implementation stop.
The planning PR itself changed no application code, deployment or installed models.

Current delivery: [Create project & build](../assistant-project-build.md) integrates
the adapted Work WIP. [Shared conversation shell](../conversation-shell.md) now
unifies composer presentation, collapsed history/tools and scroll preservation.
The [unified catalog](../model-catalog.md) now combines provider/model selection
and version guards. Reasoning, automatic model routing, draft persistence,
contextual Work and long media remain
next work. The WIP inventory below records the historical pre-delivery
checkpoint; preserve original Memory and `.tools/assistant-project-build` changes.

## 1. Current release and preserved work

| Item | Verified state at this checkpoint |
| --- | --- |
| Entry / modes | #269: editable first prompt, transactional `/api/chat/turns`, receipts, `chat|work` server policy, typed versioned defaults, migration 0020 |
| System / Settings | #270: distinct routes; General, Providers, Integrations, Access and Maintenance; separate System diagnostics; retained old maintenance redirect |
| Local selection | #271: installed GGUF selection starts no workload; first Send can load it through existing owned llama.cpp prerequisites; device IDs discovered dynamically |
| Missing conversation UX | Separate provider/model controls; existing transcript/history layout; attachment/action forms; no verified reasoning control; no unified catalog or completed shared shell |
| Video / avatar duration | Both existing request families still stop at 81 frames. Wan is 24 fps; avatar is 25 fps. Full long-media generation is not delivered |
| Live UI | `http://127.0.0.1:8765/`, release `.tools/ui-auto-model-20261014`; central record `data/acceptance/safety-redeploy-20261012/deployment.json` |
| Open PRs | None at this read-only checkpoint; recheck before implementation |

Root checkout remains `feat/memory-scope-tagged-runs` at **6ba096d**, with existing
README/architecture/Memory/status documentation and Memory UI changes plus
`docs/handoff.md`. Preserve them. Its code is older than deployed `develop`.

Two project-build WIPs also remain separate:

- `.tools/assistant-project-build`, `feat/assistant-project-build`, base **806b604**:
  original uncommitted implementation; preserve it.
- `.tools/work-project-build`, `feat/work-project-build`, base **f7387bf**:
  adaptation of that WIP to current Chat/Work, first Send and cancellation. Includes
  backend, UI and tests, but no commit/PR/merge/deployment. It composes project setup
  → worktree → coding; external executors require explicit sharing consent.
  Local projects survive a late coding/model failure. A typed cancellation chain
  follows only known same-Task parent/child pointers; it is not general graph Stop.

The latter WIP has a recorded 375-test frontend pass, successful build and read-only
desktop/mobile form checks. Its latest full Python check was still incomplete at
this checkpoint. Verify the final process/log before reporting a pass; older full
results predate its last cancellation change. Existing evidence is under
`data/acceptance/work-project-build-20261014`; logs are `/tmp/ai-station-work-build-*`.
Do not commit the `.venv` symlink. Do not deploy an image merely because it built.

## 2. Next PR: the conversation shell

Finish the visible user journey before adding more advanced configuration. Reuse
current endpoints and working result components; do not rewrite the Run engine.

1. Extract a shared composer from `NewChat.tsx` and `ConversationView` in `Chat.tsx`.
   Draft text, uploads, ordered media references, mode, search and pending request
   identity have one state owner. Keep the accepted request UUID until success;
   an intentional new Send gets a new UUID. Preserve the draft on transport failure.
2. Put history in collapsible navigation/drawer. Existing conversation shows one
   readable transcript and bottom composer, with compact title/mode/model controls.
   Keep all workstation tabs and independent Coding history; `/home` stays Dashboard.
3. Replace unconditional token-driven `scrollIntoView` with a bottom sentinel:
   follow only while the reader is near the bottom, preserve position when reading
   earlier messages, offer Jump to latest, and restore position on reopening history.
4. One attachment affordance supports upload, paste, drop and Library. Existing
   decoded file limits and vision validation remain authoritative. Render previews
   and explicit source roles/order; separate understanding an image from editing it.
   Two images with person/clothing roles must reach the actual media adapter in order.
5. Reuse inline image/video/audio/agent/coding result components. Collapse technical
   logs; show relevant progress, final player/preview, sources, download, follow-up
   and review actions. Approval stays a scoped card, not a generic confirmation.
6. Persist bounded unsent text/selection in session draft storage; no binary or secret
   persistence. Restore upload IDs only after revalidation. Clear draft on accepted
   Send/logout and scope by conversation; do not leak a draft into another project.
7. Add cursor pagination/search to history only if its current bounded list cannot
   reach older conversations. Use `(updated_at,id)` ordering, stable tie handling,
   de-duplication and selected-ID restoration; no inference for search or titles.

Close this PR only after fresh entry → reply → follow-up → refresh, scrolling during
streaming, stop, failed Send retry, long code, attachment removal, empty/offline
state, desktop/mobile and keyboard/IME checks. Avoid a second configuration sidebar.
These are acceptance outcomes; exact component extraction is at implementer's discretion.

## 3. Next PR: one model picker, then verified reasoning

Replace separate provider/model choices with the catalog described in the
[conversation plan](chat-work-experience.md#one-model-picker). Add a typed read-only
projection, not another runtime registry. Candidate item contract:

```text
model_ref, provider_key, model_key, display_name, location, runtime_kind,
availability, unavailable_reason, modalities, context_limit,
reasoning_capability, capability_provenance, config_version
```

Preserve `llamacpp:<ModelFile.id>`, existing model keys and provider secret references.
Catalog GET and selection cannot load a runtime or disclose secrets. Validate a
selected reference again at Send; snapshot provider/config/capability versions in
the Run. Keep existing clients compatible through additive fields or adapter mapping.

Searchable groups: Local · llama.cpp, Local server, External. Show human model names,
Ready/Loads when needed and external disclosure. Auto is deterministic local choice
by modality, known context fit and availability; do not choose cloud as fallback.
Allow larger fitted Coding context independently of the modest Chat profile. Make
unknown runtime/vision/reasoning capability explicit in advanced inspection.

Reasoning is a separate PR after catalog identities work. Inspect the actual owned
llama.cpp build/template and native bridge, not only upstream documentation.
The current launcher still forces `--reasoning off --reasoning-budget 0`.
Enable UI only for a verified per-request mapping or compatible owned idle-runtime
profile. Native effort, thinking toggle and token budget remain distinct; unsupported
models show no selector. A user setting cannot change a running consumer's profile.
Test normal content, reasoning-only chunks, tool calls, output exhaustion and Stop;
never fabricate thinking text or treat it as instructions. Preserve Coding's
bounded JSON and `/no_think` behavior. Details and wire limits are in the plan.

## 4. Work continuity after the project-build WIP

Review/reconcile the existing WIP instead of rebuilding it. Verify current first-Send
and mode policy tests and external scope. Then finish these distinct user outcomes:

- Name + goal creates an owned project and a coding session without path/branch forms.
  Agent/model is optional; advanced repository policies remain available elsewhere.
- One context chip identifies the explicit project, coding Task and owned worktree.
  “Now add login” uses existing continuation services on that exact session;
  New task deliberately creates a separate branch/worktree. Ask once when ambiguous.
- Show setup, coding and validation as one user task. Routing/setup success cannot
  show Ready before checks finish. Preserve usable project and reviewable work on
  failure, with retry/repair on the failed stage rather than duplicate project creation.
- Stop must cover setup → coding → validation/repair transitions atomically. The WIP
  currently covers only selected typed pointers; test the remaining transitions before
  calling it task-wide Stop. No automatic commit, publish, agent activation or rollout.

Acceptance uses temporary repositories/fake Local/Cursor/Codex adapters first. Any real
external test needs the already-authorized exact data scope or new consent if expanded.
An isolated project smoke needs matching control-plane/Runner data roots; the production
Runner cannot write project results into an unrelated isolated database's storage.

## 5. Long media: concrete implementation sequence

Follow [long-media execution](long-media-execution.md); that document contains duration
math, audio alignment, ownership, publication, recovery and resource contracts.

| Increment | Implement | Gate before advertising |
| --- | --- | --- |
| Foundation | Versioned immutable media plan, uniquely keyed stage attempts, RunDependency graph, aggregate job projection, atomic graph Stop/resume | Fake races/recovery plus real disposable CPU concat/mux/full-decode tests |
| Safe resources | Atomic RAM + per-device VRAM admission, bounded encoder concurrency, persisted ownership/reservations and fair resource waiting | Two claimers cannot over-admit; no external process eviction; uncertainty retains reservations |
| Wan | Bounded `4n+1` windows, qualified tail-frame conditioning, exact overlap trim, fixed CPU composition, duration UI and inline final artifact | Real ≥15 s continuous and ≥30 s deliberate shots; inspect every join and complete decode |
| Avatar | Flash-compatible window adapter, canonical whole audio, absolute sample/frame offsets, identity/tail context, one final audio mux | Real 30/60 s speech, final phrase audible, frame timing and lip/identity continuity |
| Two GPUs / longer profiles | Measured independent-shot parallelism, sequential fallback; separately qualified 120 s avatar and higher limits | Combined peak RSS/VRAM fit, mixed Chat/media responsiveness and Stop/restart/resume |

Do not reinterpret a montage as an uninterrupted take. Do not loop/stretch a short
clip, silence-trim speech, fake smoothness with frame interpolation alone, or merely
raise `81` in validators. A generated scene may take substantial time; show measured
stage progress without invented ETA. Expose the largest *qualified* duration/profile.

Read-only installed-source recheck confirms ComfyUI **387f98aa** and EchoMimic
**7e89489**. Flash imports `src/pipeline_wan_fun_inpaint_audio_2512.py` and builds
audio embeddings shaped `[F,5,12,768]` before the batch dimension; preview imports
a different pipeline and slices embeddings with `frame_index * 2`. Establish the
flash adapter's own frame mapping and context mask; copying preview indexing is wrong.
Its accepting video/mask inputs is a research entry point, not long-video proof.
Keep installed code/checkpoints read-only. No downloads or driver changes.

The workstation recheck sees two 12288 MiB RTX 3060s and about 32 GiB system RAM.
Those observations are evidence for admission measurements, never application constants.
Use one heavy media job initially. Enable two independent GPU jobs only after their
combined offload/encoder RAM and individual VRAM peaks fit; llama.cpp multi-GPU support
does not qualify Wan/Echo sharding. Qualify continuous dependencies sequentially.

## 6. Efficient execution and handoff rules

Start a focused feature worktree from updated `develop`, inspect changed files and
open PRs, then implement the first unfinished increment above. Preserve all WIP.
No broad audit/rewrite or hardware smoke for an untouched feature. Focused tests
while editing; repository-required checks once on the reviewed final head; rerun only
affected validation after a meaningful fix. Use `PYTHONPATH=backend:host-runner` and
Docker-backed `scripts/frontend.sh` in isolated worktrees.

For each PR: full diff review, successful local checks as authorized, squash to
`develop`; never touch release branches. Existing AI Station restart permission
allows deployment during implementation with DB backup and ownership checks.
The historical planning turn performed no deployment. Implementation is now
resumed with existing restart authorization. Preserve data and distinguish fake
integration, real CPU and real GPU/provider acceptance.
After switching model, begin with the shared conversation shell or reviewed Work WIP;
do not regenerate this plan or repeat #269–271. Long media remains a required
deliverable, not a cosmetic unavailable screen or a promised checkbox.
