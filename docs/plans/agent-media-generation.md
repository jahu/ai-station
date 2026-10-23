# Persistent agents can create media

Status: implemented candidate with compiled UI and real GPU agent qualification;
full release gates and backed-up rollout remain. The deployed release is Music #361.

Image/music scopes, nullable migration 0032, API/duplicate handling, natural
AI-assisted disabled drafts, editor and inline results reuse existing media
services. Fixed descriptions need no text model. Goal-based descriptions can use
completed reviewed research observations; only the creative text may change.
Supplied lyrics, references, model/backend, GPU and generation settings remain
frozen. Drafting cannot invent Library IDs or lyrics. Output-specific native
readiness blocks activation when the selected engine is unavailable.

The shared absolute deadline reaches typed native requests and a persisted
owned-process timer. CPU integration covers expiry without a worker, restart,
forked descendants, replay, reused PID rejection, queued/running Stop and resource
release. Worker publication verifies the exact agent definition, effective
permissions, source hashes/lineage and preparation receipt under the Task lock.
No Runner HTTP occurs inside media publication. Final success notices wait for
actual media rather than preparation.

Compiled browser qualification passed at 1440px and 390px: edit/save/enable/run,
fixed output without a text model, supplied lyrics, music playback/image results,
Library/refresh, missing-reference validation, whole-Task Stop before native
launch and no horizontal overflow. These used temporary databases and fake
native outputs, not real image/music inference. Focused factory/worker tests and
590 UI tests passed. Real temporary-database agents created a 512×512 Juggernaut
image and 10-second ACE-Step instrumental through actual native execution, with
Library artifacts, inherited owned deadlines and released resources. The
verification resumed the existing successful image after correcting a verifier
that confused native exited/0 with the domain succeeded state; it did not repeat
image generation. No active operator LLM needed stopping; that empty ready-model
state was preserved. Full release gates and deployment remain.
Evidence: ignored data/acceptance/agent-media-generation-20261023/.

Automatic lyric writing and agent video/avatar scopes remain separate work.

## Result and user flow

An operator can create a disabled agent, select **Create media**, describe its
goal, review the output type and bounded generation settings, then enable it.
Run now and saved schedules create ordinary agent Tasks. The agent workspace
shows preparation, generation, playable/visible results, Library links and Stop.
An agent that researches a topic and creates an image must preserve its reviewed
public query/URLs and source artifacts alongside the generated result.

Use one registry tool and a discriminated, reviewable output scope. Images and
music reuse `create_image_run` and `create_music_run`; they are not separate agent
execution engines. Extend the same scope to existing speech, video and avatar
services with their required references and tested runtime contracts. Do not
advertise an output type until its entire chain is wired and verified.

## Stored authority

- Add nullable `Agent.media` JSON with an Alembic migration after `0031` and an
  optional typed `AgentSettings.media`. Existing agents retain null. Update
  serialization, update/duplicate/factory handling and frozen Run snapshots.
- The scope chooses the output kind and existing typed request settings. It
  contains no shell, interpreter, model URL, endpoint, secret or host path.
  Image references are reviewed Artifact UUIDs, rechecked for availability and
  ownership before dispatch through the existing image service.
- Media scope requires the selected Create media tool. Reject conflicting
  coding/data/market/Git/runtime scope. Research and scoped memory remain
  composable through their existing explicit permissions and reviewed targets.
- A generated creative description may change only the description/lyrics
  fields permitted by the saved scope. The model cannot change reference IDs,
  backend, duration, dimensions, GPU selection or permissions. A fixed reviewed
  description requires no preliminary text inference.
- Registry/activation readiness reflects real native capabilities. Incomplete
  adapters remain unavailable. Saving or inspecting a draft executes nothing.

## Publish and execute

1. `schedule.launch_agent` validates and freezes the same scope for manual and
   scheduled execution. Continue using the existing agent workflow and Task.
2. `planned_steps` and `publish_steps` retain approved research/memory steps.
   Add a bounded preparation/publication stage and the selected media child.
   Use existing dependencies; do not launch native work in these handlers.
3. Observe runtime readiness outside the child-publication transaction. Freeze
   source/artifact provenance. A local creative stage, when requested, uses
   existing model admission/leases and stores a validated JSON artifact.
4. Under the existing Task lock, verify the exact parent, Agent snapshot,
   effective permissions, prepared result and source hashes. Publish the media
   child with the same Task/agent/parent, stable operation identity and shared
   absolute deadline. Child publication and parent completion commit together.
   A lost response/recovery cannot duplicate GPU work.
5. The existing media executor owns resource admission, native launch, process
   group, output validation and artifacts. Propagate the agent deadline through
   a genuine shared media deadline contract; do not disguise it as a coding
   deadline or rely only on the native wrapper's one-hour ceiling.
6. Final workflow reporting waits for actual media success and references its
   saved artifact. Failure/cancellation preserves observations and errors,
   produces no fictional finished media and never reruns external effects.

Task-wide Stop must reach preparation, queued dependencies and the exact owned
media process. Recovery inspects existing work instead of replaying generation.
Edit/pause/enable semantics and current immutable historical Runs stay intact.

## UI and qualification

Add an output card to the existing agent editor with type-specific, familiar
media settings; keep GPU/seed advanced. Preview the selected source images and
make source removal explicit. Show the resulting image/audio inline in the
results-first agent workspace, preserving Library and Run inspection. A tool
name or raw definition JSON must not be the normal user experience.

Verify migration/legacy agents, activation/schedule snapshots, fixed and bounded
creative descriptions, source/hash/permission checks, unavailable engines,
publication receipts, shared deadlines, failures, Stop and recovery. Normal
checks use temporary DBs/fake executors and never consume GPU/cloud tokens.
Qualify the compiled desktop/phone workflow and existing Chat/Work regression.
Then run short explicitly opted-in real image/music agent cases using installed
models, inspect actual artifacts and restore the operator model profile.
Review the full diff, required local checks and final image before a PR to
`develop`, squash merge and backed-up deployment. No production branch merges.
