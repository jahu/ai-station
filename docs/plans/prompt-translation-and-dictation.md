# Optional media prompt translation and Chat/Work dictation

Requested 2026-10-25. Dictation is delivered through PR #441 and deployed;
optional image-prompt translation is qualified for PR #442. Standalone
Video/music translation is qualified for PR #443 under the [shared workflow contract](media-language-workflows.md). These are
additions to platform completion. The Krea image delivery is complete; the original
planning worktree is preserved.

## Optional translation for media models

Current image execution/approval/retry contracts and qualification gates are in
the [implementation record](media-prompt-translation-implementation.md). No new
translation feature is deployed until its release gates and actual-model checks pass.

Goal: let the operator write naturally in Polish while optionally translating
model-facing instructions into the language recommended for the selected model.
Translation may improve adherence; do not claim a universal English/Chinese
advantage or guaranteed quality improvement without model-specific comparisons.

- Put **Translate media prompts** in Settings → Generation, initially off. Keep
  one simple switch; an advanced section selects the installed local translator
  and default target (English initially). Model profiles may declare a reviewed
  preferred language; never infer Chinese merely from a model's origin.
- Apply the same policy in Images, Video, Audio/music and orchestrated Chat/Work
  media actions. Add a compact per-request override next to generation options;
  inherit the station default, with no settings hunt required for each prompt.
  Ordinary conversation and agent instructions are not globally translated.
- Translate only model-facing descriptive instructions, including negative
  prompts when supported. Preserve source-image roles/order, identity constraints,
  model tokens, LoRA triggers, weights, names, numbers and explicit quoted text.
  Lyrics, speech text, subtitles and requested text inside an image retain the
  user's language unless the user separately requests their translation.
- Translate faithfully, without embellishing, sanitizing, expanding or otherwise
  changing intent. Matching target-language input can pass through unchanged.
  If translation fails, show Retry / Use original; do not silently claim success.
- Keep the original user message intact. Show a collapsed **Prompt sent to model**
  receipt with original, translated text, target language and translator identity.
  Allow review/edit before dispatch via advanced preview; a retry reuses its
  recorded effective prompt unless the user explicitly asks to translate again.
- Prefer a configured installed local LLM. No automatic downloads or hidden cloud
  calls. External translation requires the existing explicit provider selection
  and external-AI permission. Page text and references remain data, not translator
  instructions. Bound input/output sizes and validate protected tokens.
- Perform preparation in the worker through the existing Task → Run → Events →
  Artifacts lifecycle; use an inspectable preparation child Run when inference is
  required. Snapshot policy, source/effective prompts and translator configuration
  before media dispatch. Existing resource scheduling must release the translator
  before media GPU allocation when required, avoiding competing GPU reservations.
  Stop/recovery follow ordinary Run contracts; no inference in HTTP handlers.

Deliver first for installed image adapters, then reuse the same service for
operational video/music adapters. No fake support for unavailable capabilities.
Acceptance: Polish→English, already-English passthrough, explicit per-run off,
protected tokens/quoted Polish text, negative prompts, two-reference ordering,
failure/Stop/retry, no hidden external traffic, and original/effective receipts.
Compare identical seeds/settings with translation on/off on actual installed
models; report observed adherence and artifacts, not an assumed improvement.

## Dictate a prompt directly into Chat and Work

Existing [recording capture](../chat-recording.md) attaches audio for a later
conversation turn. Existing [offline transcription](../audio-transcription.md)
already produces verified text. Reuse both; dictation is a separate composer
action that inserts editable text before the user sends the actual request.

- Add an accessible microphone **Dictate** beside the Chat/Work composer, on
  desktop and mobile. Retain **Attach recording** for audio analysis; distinguish
  these actions in labels/tooltips rather than forcing a transcription mode.
- Flow: click → microphone permission → recording/timer → Stop → local
  transcription progress → editable transcript in the draft → ordinary Send.
  Never submit or execute the dictated request automatically. Preserve existing
  draft text, caret position and attachments; show Insert/Replace if edits during
  transcription would otherwise be overwritten.
- Reuse native validated uploads, offline Whisper, duration/byte limits, managed
  process ownership and cancellation. Transcription gets its ordinary Task/Run;
  creating that Run does not create an assistant response or execute Work tools.
  Record source/transcript provenance under existing artifact rules and make the
  retained recording visible; do not introduce hidden audio retention.
- Show Cancel/Stop, retry without re-recording, language Auto/Polish in advanced
  preferences, permission/error feedback and disabled/unavailable reasons. Release
  the microphone on finish, cancellation, navigation and component unmount.
- Microphone capture needs a browser secure context: qualify localhost and HTTPS
  LAN/remote access. Plain HTTP LAN must explain how to enable HTTPS and offer
  audio-file transcription; do not claim microphone capture works there. Setting
  up HTTPS/Tailscale transport remains a separate authorized deployment change.
- Acceptance: desktop/mobile layouts, keyboard/screen reader controls, permission
  denied, absent device/runtime, recording limits, cancel during transcription,
  navigation cleanup, draft edits/races, no automatic Send, Polish recognition,
  and actual physical microphone tests over supported secure connections.

Add both workflows to the final operator QA workbook, with expected outcomes,
room for actual results and links to inspectable Runs/artifacts. Documentation
alone does not count as delivered functionality.

### Dictation implementation contract

The shared ConversationComposer exposes **Dictate** in both new and saved
Chat/Work conversations, including project continuations. **Dictation options**
contains Auto/Polish and the audio-file fallback. The existing attachment action
**Record audio** remains distinct: it attaches a recording for later analysis.

Capture reuses RecordingButton's formats, timer, limits and microphone cleanup.
Finish queues `/api/audio/transcription/runs`; it never calls a conversation
endpoint. Draft version and selection are snapshotted before microphone permission
or file selection. A changed draft requires Insert at cursor / Replace draft /
Keep my draft. The combined draft has the existing 32,000-character limit.

An optional UUID `client_request_id` binds direct transcription submissions to a
namespaced Task identity and exact recording/language hash. Repeated or concurrent
submission returns the same Run, including after terminal completion or unavailable
runtime. A conflicting scope returns 409. Existing conversation children keep
their existing Task, permissions and ordinary lifecycle; no schema migration is
needed. Confirmed failed/empty/stopped transcription can be explicitly retried as
a new request with the saved recording; uncertain acknowledgements keep their
identity and language. Stop and navigation cancel only the owned Run, including
late successful acknowledgements. A failed acknowledgement may leave an inspectable
Run in history; it is never blindly launched a second time.

Recordings are retained as normal Library inputs and transcript artifacts retain
their source lineage. Visible links provide the source, transcript and Run before
Send. Dictation itself cannot grant Work tools, load a conversation model, or send
audio to a cloud provider. After the operator edits and Sends, text uses the normal
explicit conversation/provider rules. No physical-microphone or HTTPS deployment
acceptance is claimed by fake-device browser tests.

Qualification (2026-10-25): 4,001 normal Python cases (3,992 passed, nine explicit
opt-in skips), all 830 frontend tests, format/lint/types/build and six QA exporter
checks passed. Exact Docker source/assets, all Compose configurations and isolated
API/worker/SQL/SSE smoke passed. Actual compiled 1440px Chat and 390px Work used
approved Polish audio, Chromium MediaRecorder and native CPU Whisper; source-linked
transcript artifacts, no automatic turn, cursor/race protection and compact mobile
controls passed. The current tiny Whisper profile still needs operator correction
of recognition mistakes; this is not a perfect-transcription claim. Physical
microphone and phone HTTPS capture remain explicit operator QA cases.

Reviewed head: `a77fa9e81d99d52424c003135de5120bb34f4b98`; develop squash:
`0f218f0a3e9b7cae5ec6e1fe7ec0437087d0d9ed`. Evidence:
`data/acceptance/chat-dictation-20261025`. Controller-only deployment preserved
the native Runner, managed GPU models, E5 configuration/indexes, all prior data
and LAN authentication. The dictation release brought the Polish QA catalog to 137 cases;
the whole-platform release workbook remains a later handoff gate.
