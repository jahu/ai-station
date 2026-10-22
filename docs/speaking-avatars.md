# Typed speech → Avatar workflow

The current workspace and conversational workflow compose typed speech with
[full-recording media jobs](long-media.md), up to 60 seconds, using audio-aligned
windows and one canonical speech timeline. Short preview controls and the older
direct-Run workflow below remain available. They do not define the default
full-recording behavior. [The longer-term plan](plans/long-media-execution.md#6-full-speech-echomimic-without-audio-truncation)
retains broader narration/quality profiles; the real 30-second acceptance is
[reported separately](long-avatar-qualification.md#executed-2026-10-15).

## Compatible short-Run workflow (earlier implementation)

In Avatars or Video, select **Type what to say**, attach a portrait and a short WAV voice reference, and enter Polish speech text. **Use a recording** retains the existing direct animation path. Scene direction, quality, clip length and advanced GPU/steps/seed remain available. The clip animates the start of the generated speech for the selected length; it does not promise to cover an arbitrarily long script.

The Platform assistant accepts the optional **Words to say** field with one portrait and one WAV. It also recognizes explicit current spoken words, for example “Zrób awatar, który powie: Cześć!” or `Animate this portrait saying "Hello there"`. Ordinary portrait animation still uses the recording directly. Prior conversation instructions and attachment contents cannot select spoken text or authorize additional steps.

The request creates an ordinary Chatterbox Run under an avatar Task. Its immutable parameters include validated avatar settings and the explicit portrait ID. After known successful owned-process completion, speech artifact registration, publishing the EchoMimic child and completing the speech Run commit atomically. The child consumes the generated WAV, preserves the same Task/conversation, GPU request, effective read/write permissions and trigger, and creates an MP4 linked to the portrait and speech. The WAV retains voice-reference lineage. Both artifacts remain in Library.

Failure, cancellation or uncertain speech completion publishes no avatar. Existing private Runner operations, GPU locks, offline installation configuration, owned process groups and recovery policy remain unchanged. A restart after commit finds the queued animation; an uncertain dispatched process is never blindly repeated. Stop follows the active stage, and canceling animation preserves completed speech. Automatic retries and new downloads are not introduced.

Avatars retains the first Run in its URL and reads the bounded same-Task chain through `GET /api/avatars/runs/{id}/workflow`. The image workflow and avatar workflow share read-only traversal with explicit executor allowlists, parent/Task checks, cycle/length bounds and secret redaction. A failed animation is visibly failed even though speech succeeded. The assistant's ordinary Task projection shows both stages and results.

Text is limited to 1000 characters. Existing WAV/image checks and EchoMimic duration/clip bounds still apply. This workflow requires the already-installed Chatterbox and EchoMimic adapters; it is not general text-to-video or a music runtime.

A Stop request that still references the just-completed first stage resolves the validated active child, closing the completion/UI-refresh race. It never traverses another Task or executor family.
