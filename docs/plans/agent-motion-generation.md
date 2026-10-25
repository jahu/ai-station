# Video and avatar output from persistent agents

## Natural video draft correction — 2026-10-25

The release audit's actual Qwen3.5 9B run reproduced failed natural video drafting:
the proposal JSON schema advertised the inherited short-clip `frames=49` even
though duration-based agent requests reject that field. The first real response
included both timing controls; its bounded correction removed duration while
retaining frames, so both responses were invalid. No media was generated and
the isolated owned runtime was stopped; production records were untouched.

Hide only this non-proposal field from `AgentVideoRequest`'s generated JSON schema
with Pydantic `SkipJsonSchema`, retaining its existing snapshot exclusion and
explicit-input rejection. This does not accept/drop untrusted model fields or
weaken duration/resource validation. The actual factory prompt regression fails
before the change; image/music/avatar proposals retain their existing schemas.
Real requalification and final local/image gates are still required. Evidence:
`data/acceptance/agent-video-release-20261025/`. Earlier receipts remain unchanged.

Status: scene-video agents are implemented through the existing long-media
controller. The optional native deadline prerequisite (#366) is deployed.
Whole-speech avatar agent scopes are implemented and deployed in #368; new real
agent GPU qualification is tracked separately from the dedicated workspace.
Image, music and speech agents retain their delivered contracts.

The prerequisite adds private optional deadlines to Wan, EchoMimic and CPU
composition and forwards the frozen Run expiry from their current executors.
33 new focused CPU cases pass, including actual owned sleeping processes stopped
without any worker, invalid/expired budgets, worker resource cleanup, composition
forwarding and public-form rejection. Existing motion and process-ownership
regressions pass. The source and frontend qualification are recorded under
data/acceptance/motion-media-deadlines-20261023/. No new real GPU video/avatar
generation is claimed by this transport/lifecycle change.

The prerequisite release (#366) passed all 2436 normal Python/Runner cases:
2427 passed, 9 opt-in skips, zero failures. Ruff formatting/lint and Docker/Compose
checks passed. The frontend is byte-identical to #365, reusing its 596 passed tests,
formatting/lint/typecheck/build and compiled desktop/phone qualification; the built
image has those same assets. Final review and rollout evidence remain separate
from these CPU checks.

## Current implementation increment

Scene-video scopes now reuse the existing long-video settings, preparation
receipt, same agent Task, segmented Wan Runs and final CPU composition. Pure
video schemas avoid a settings/executor import cycle. Goal preparation changes
only the shared prompt; duration, shots, first frame, quality and GPU remain fixed.
The current profile observation is obtained before locked publication and passed
explicitly, avoiding native HTTP inside that transaction.

Every segment and final composition receives the same immutable absolute budget.
Only final composition success emits the ready notice; completed segments remain
partial results. An agent cannot resume an old film with a fresh budget: Run now
or the ordinary agent retry creates a new reviewed workflow instead. Sources and
prepared JSON retain transitive lineage through segment artifacts. Each queued
segment rechecks first-frame availability, metadata and actual bytes before a
native dispatch is recorded; changed or trashed sources fail without launching
GPU work or retaining a reservation.

The editor adds Video, full duration, continuous/shot motion, optional storyboard
and first-frame selection. Advanced controls reuse local GPU selection. The
workspace reuses existing long-media progress, playback, Library and Task Stop.
This increment passed all 2455 normal Python/Runner cases (2446 passed,
9 opt-in skips, zero failures), Ruff formatting/lint, all 598 UI tests,
formatting/lint/TypeScript/production build, Docker backend/assets and both Compose
variants. Compiled 1440px/390px checks cover scene editing, first-frame upload,
Save/Enable/Run, full playback, Library, reload and Task Stop without overflow.
These use test native segments and real CPU composition, not a GPU model.
Review, backed-up rollout and a real normal-worker sample are recorded separately
in data/acceptance/agent-long-media-output-20261023/.
Whole-avatar agent output is now delivered through the increment below; its
existing dedicated workspace remains available.

## Delivery sequence

1. Carry the existing optional absolute owned-process deadline through Wan,
   EchoMimic and CPU composition. Use the same native ProcessManager journal,
   SIGTERM/SIGKILL ownership checks and restart-restored timer as speech/music.
   Add only private typed request fields; public workspace forms cannot set them.
   Calls without a deadline retain their current behavior. This prerequisite does
   not enable video/avatar agents or automatically put a budget on ordinary jobs.
2. Extend the reviewed discriminated media scope with long scene video and
   whole-speech avatars. Video uses the existing duration/composition/storyboard
   contract. Avatars require reviewed portrait and audio/voice Library references;
   disabled drafts may wait for selection. Freeze source identity, hashes, sizes,
   actual files and runtime profile; models cannot choose UUIDs or runtime paths.
3. Publish via the existing media preparation receipt and Task lock into existing
   media jobs. Creative preparation may change only the main scene instruction
   or bounded spoken words. Keep duration, storyboard, portrait, voice, quality,
   GPU, permissions and absolute deadline controller-owned. Every planner,
   segment, generated speech and final composition inherits that same expiry.
   A replay/resume must never extend it. Final agent success requires the verified
   composed video artifact, not its first segment or prepared prompt.
4. Retain Task-wide Stop through queued/running stages, dependency failure,
   worker/native restart, uncertain ownership and resource admission. Use existing
   operation keys; never duplicate generation on lost responses. Expiry must be
   enforced by native ownership even while the worker is unavailable.
5. Add familiar Video/Avatar output cards to the agent editor, with source previews,
   clear whole-output duration and advanced resource/quality settings. Natural
   drafts stay disabled; missing source or unavailable engine blocks activation.
   Inline final playback, step progress, Library/reuse and reload preserve UX.

## Qualification

Use temporary databases and fake installed profiles/processes for schema,
permissions, immutable inputs, publication receipts, shared budget, Stop,
failure, recovery and no-budget regressions. Native tests exercise real owned
sleeping CPU processes with short deadlines; they require no GPU or download.
Use compiled desktop/phone browser checks for editor, source selection, final
playback and reload. Run the required local full checks, inspect the full PR diff
and built image, then back up and deploy through develop. Qualify a short actual
existing-model agent video/avatar only after the complete chain is operational;
record real duration/profile and preserve the operator's actual model state.

## Whole-avatar agent increment

The candidate reuses ordinary Chatterbox, the deferred avatar planner, EchoMimic
windows and verified CPU composition. Pure full-avatar settings avoid an import
cycle. Avatar drafts may wait for a portrait and WAV; both are required for
activation. A read-only native capability checks the configured existing
installation and GPU without starting a model. Generated Polish speech also
requires the existing speech capability.

One immutable expiry covers preparation, generated speech, planner, every
animation window and final assembly. The pending speech handoff must match its
actual planner and successful same-Task audio; receipts cannot replace a budget
or duplicate work. The final composition retains its workflow ancestry.
The planner observes expiry before publication.

Image/audio IDs, paths, sizes, checksums and MIME roles are frozen. Original
portrait/voice bytes are rechecked before speech/planning. The generated canonical
audio is bound to the actual successful speech Run and its Artifact; all inputs
are rechecked again before each animation dispatch. Existing video snapshots
without MIME roles remain compatible. Only final assembly emits a positive ready
notice; failed, canceled and incomplete stages preserve evidence without a
fictional finished avatar.

Goal mode may change only spoken words (Polish, 1000 characters) when generating
speech, or the motion prompt with an existing recording. Portrait, voice,
recording, size, steps, seed, GPU and the shared expiry stay fixed. Natural
proposals leave source IDs null for operator selection. Ordinary workspace
requests retain their existing contract.

The editor supports both speech modes, separate source previews, draft saving
before source selection and advanced quality/GPU controls. The workspace shows
the same full-media progress even while the planner is pending, saved spoken
words, final playback, Library and Task Stop. Normal CPU checks use fake native
models and real video composition. Review/full release checks and actual
hardware qualification are recorded separately; no new real avatar result is
claimed by these tests.

The avatar increment's final normal CPU suite passed all 2485 cases (2476 passed,
9 opt-in skips, zero failures), including explicit rejection of modified handoff
settings. All 601 UI tests, format/lint/typecheck/build and compiled 1440px/390px
checks pass. Browser coverage exercises both speech modes, pending drafts, source
upload/removal/reselection, enable/run, full playback, Library, reload and Stop;
it uses fake inference and real CPU composition. Docker/source/assets and Compose
qualification, review and rollout are recorded under
data/acceptance/agent-avatar-output-20261023/. Actual new agent GPU qualification
remains separate from these checks and requires available workstation resources.

The previous real 30-second standalone avatar took about 35 minutes at
384px/eight steps. Review the agent runtime budget for longer/high-quality jobs;
the tested whole-output chain does not imply real-time rendering. The software
preserves existing applications and waits for admitted GPU/RAM rather than
silently reducing the reviewed quality or resource requirements.
