# Ordinary recording attachments in Chat/Work

Use the ordinary **Attach files** entry for one WAV, MP3, M4A, Ogg, WebM or FLAC
recording. The existing recording uploader validates bytes and saves an owned
Artifact; never decode binary audio as text or embed it in the prompt. Keep the
current question while uploading and on failure. Show the stored filename,
a playable preview and a clearly named Remove recording action before Send.

Reuse the shared conversation upload mutation/cache/error ownership. Recordings
cannot mix with text/PDF/data/images in the ordinary selector. Existing explicit
media actions, coding/project scopes, exact Web queries/rendering and bound Work
continuations keep their authority; unavailable generic audio selection explains
how to choose the existing recording tool. Selecting audio clears one-turn Web,
uses the existing Auto recording router, and does not change the conversation
provider/model or Chat/Work mode. Suppress irrelevant reasoning controls while an
input recording is selected.

The backend is unchanged: explicit transcription requests use the local CPU
transcription child; other questions compose transcription and the selected
conversation model through the existing same-Task dependency. The privacy text
must distinguish local transcription from the selected model's answer. Existing
source validation, duration/20 MiB bounds, permissions, Stop, recovery, transcripts,
Artifacts and inline audio results remain authoritative. Do not install models,
download runtimes or add another execution architecture.

Qualification: first/saved conversations and desktop/phone compiled UI; storage,
file replacement/removal, wrong/mixed/oversized selection, error persistence,
current prompt, request scope, transcript/answer and reload. Run the full UI gate,
Docker/Compose and compare unchanged backend/Runner against the reviewed #376
full local gate. Reuse real qualified transcription only when the exact existing
contract and source are unchanged; any new real audio test must be explicitly
identified and use actual normal worker/native transcription, never fake text.

This increment is active, not a declaration that the complete platform is done.
