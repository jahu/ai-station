# Video and avatar output from persistent agents

Status: the optional native deadline prerequisite is implemented and qualified
in CPU tests. Image, music and speech agents are delivered.
Video/avatar agent scopes remain unavailable. Reuse the existing long-media
controller rather than adding a short-clip-only agent engine.

The prerequisite adds private optional deadlines to Wan, EchoMimic and CPU
composition and forwards the frozen Run expiry from their current executors.
33 new focused CPU cases pass, including actual owned sleeping processes stopped
without any worker, invalid/expired budgets, worker resource cleanup, composition
forwarding and public-form rejection. Existing motion and process-ownership
regressions pass. The source and frontend qualification are recorded under
data/acceptance/motion-media-deadlines-20261023/. No new real GPU video/avatar
generation is claimed by this transport/lifecycle change.

The complete normal Python/Runner qualification passed all 2436 collected cases:
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
prepared JSON retain transitive lineage through segment artifacts.

The editor adds Video, full duration, continuous/shot motion, optional storyboard
and first-frame selection. Advanced controls reuse local GPU selection. The
workspace reuses existing long-media progress, playback, Library and Task Stop.
This candidate still requires complete release/browser/real-model qualification.
Avatar agent output remains planned and unavailable; its existing dedicated
workspace is unchanged.

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
