# Spoken output from persistent agents

Status: next implementation candidate after image/music agents (#362) and the
verified idle-model RAM admission correction (#363). Speech is not an operational
agent output until this entire chain is wired and qualified.

Reuse Create media, the agent Task/workflow and the existing local Chatterbox
executor. No model download, separate speech agent engine or additional host
access is needed. Existing supplied-lyrics music and image scopes stay intact.

The current source candidate has pure shared SpeechRequest settings, disabled
reviewable scopes, required voice selection at activation, a native configuration
capability endpoint and optional owned deadlines. Worker publication reuses the
existing Audio service with immutable voice/source hashes and preparation receipts.
CPU fake-bridge tests cover fixed output without a text model, bounded Polish
text preparation, source changes, Task Stop before publication and native expiry
without a worker. The combined Audio/image/music/agent-draft regression has
93 passing tests; this is not a real speech-model or full-release qualification.
`SPEECH_AGENTS_ENABLED` remains false until editor/results, natural drafting,
remaining lifecycle contracts and release checks are complete. No new version is
deployed from this candidate.

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
