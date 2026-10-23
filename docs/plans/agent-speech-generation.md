# Spoken output from persistent agents

Status: implemented PR #364 candidate after image/music agents (#362) and the
idle-model RAM admission correction (#363). Backed-up deployment and real
normal-worker voice acceptance remain; no real speech-agent result is claimed yet.

Reuse Create media, the agent Task/workflow and the existing local Chatterbox
executor. No model download, separate speech agent engine or additional host
access is needed. Existing supplied-lyrics music and image scopes stay intact.

The source candidate now includes the shared speech scope/voice validation,
existing Audio publication with immutable source hashes and receipts, a native
readiness endpoint and owned deadlines. Fixed text skips the language model;
goal mode prepares only bounded Polish text. Natural drafts keep their voice
unset for review and reject invented UUIDs. The editor supports WAV upload and
Library selection/removal, saving a pending voice draft, advanced GPU selection,
inline playback and existing Library/Avatar source actions.

CPU regression covers fixed/goal output, actual source changes, missing/invalid
voice activation, Task Stop before and after dispatch, native expiry without a
worker, receipt replay without Runner HTTP and stale-worker cleanup without
replaying. The combined focused check has 101 passing tests. Compiled browser
checks passed at 1440px and 390px for pending-draft save, voice upload/selection,
activation, Run now, Stop, PCM playback, Library and reload persistence without
horizontal overflow. These use temporary databases/fake native outputs, not a
real speech model. A discovered editor revision issue is corrected: untouched
settings refresh after Enable/Pause; unsaved changes remain preserved for review.

The speech implementation gate is enabled in the candidate following these
contracts. Complete Python/Runner checks pass across four isolated normal CPU
shards (2403 cases, 9 opt-in skips, zero failures); all 594 UI tests, formatting,
lint, TypeScript and production build pass. Review/rollout and real voice
generation remain. No candidate version is deployed yet.

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
