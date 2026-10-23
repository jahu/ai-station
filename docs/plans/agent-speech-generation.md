# Spoken output from persistent agents

Status: delivered in PR #364, deployed and qualified with the normal worker.
A reviewed existing Library voice and goal-based local text preparation produced
an actual non-silent 7.48-second Polish WAV on GPU 0. The result is in Library;
the sample agent is paused. No model download was required and the source voice
bytes were unchanged. Evidence: data/acceptance/agent-speech-generation-20261023/.

Reuse Create media, the agent Task/workflow and the existing local Chatterbox
executor. Fixed text skips the language model; goal mode prepares only bounded
Polish text. Natural drafts leave voice selection for review and reject invented
UUIDs. The editor supports WAV upload, Library selection/removal, saving a pending
voice draft and advanced GPU selection. Clean settings refresh after Enable/Pause;
unsaved edits are preserved and must be reloaded before replacing a newer revision.

The player now shows the exact saved spoken text from its speech Run, independently
of any Library rename. Refresh retains the script. This is the input used to
synthesize the voice, not an independently verified transcription. Music and other
audio outputs do not receive a speech label. Playback, Library and reuse actions
retain their existing behavior; this display adds no execution permission.

The speech release passed all 2403 collected Python/Runner cases (2394 passed,
9 opt-in skips), 594 frontend tests, formatting, lint, TypeScript, production build,
compiled desktop/phone checks and image/Compose checks. Live checks verified
backup integrity, authentication, persistence, worker/scheduler and native source
identity. The UI-only spoken-text follow-up reuses this unchanged backend/native
qualification and separately validates its changed frontend and built image.

## Reviewed scope and authority

Add `kind: speech` with the existing text/GPU settings, a reviewed Library WAV
voice reference and fixed/goal text policy. Disabled natural drafts may omit the
reference; activation requires the operator to select it. Never invent UUIDs or
voice files. Extract the pure SpeechRequest schema without changing the public
Audio request contract. JSON scope storage needs no new database column.

Fixed text skips the LLM. Goal mode writes at most 1000 characters of Polish
speech from the saved goal and completed observations; only text may change.
The selected voice, GPU, permissions and output settings are immutable. The
current adapter speaks Polish; do not advertise other languages or unlimited
scripts. Automatic lyrics and video/avatar agent output remain separate work.

Freeze WAV ID/path/size/SHA and verify the actual bytes before publication.
Activation rejects missing, trashed, invalid or unavailable references and an
unconfigured engine. Native readiness checks existing Python/script/cache/GPU
without launching inference or downloading files.

## Existing execution chain

Preparation publishes `create_audio_run` under the same Task lock and receipt
contract as image/music, binding its JSON preparation artifact and voice lineage.
There is no Runner HTTP inside publication. Carry the shared absolute deadline
through AudioExecutor and typed AudioRequest to the existing native ownership
manager. Stop, native expiry, worker recovery, GPU/RAM reservation and owned idle
model handoff reuse current infrastructure. Preserve existing ordinary speech
calls without an internal deadline.

Final success and in-app notices require the actual WAV, not preparation. The
agent workspace uses the existing speech player/Library actions and truthful
step names. Keep voice/reference selection and creative direction prominent;
GPU remains advanced. Natural drafting and Work create disabled definitions;
review/activation remains separate.

## Verification and rollout

Cover legacy Audio schema behavior, disabled drafts, voice selection/removal,
activation readiness, source/hash/permission changes, fixed/goal publication,
receipt replay, inherited deadlines, Task-wide Stop, failure and recovery with
fake executors/temporary databases. Inspect compiled desktop/phone editor and
results. Run the required full checks, source/assets and Compose verification,
review a PR to develop, then back up and deploy. Qualify a short real agent WAV
using an existing reviewed voice and preserve the operator's actual model state.
No unexecuted real speech test may be reported as successful.
