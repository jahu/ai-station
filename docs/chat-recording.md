# Recording in the conversation composer

**Dictate** beside Send turns speech into an editable draft in both Chat and
Work. Stop recording starts local CPU transcription; it never Sends or starts
the dictated task. Dictation options offers Auto/Polish and **Transcribe an audio
file**. Existing text, cursor position and attachments are retained. If you edit
while transcription runs, choose Insert at cursor, Replace draft or Keep my draft.
The recording and transcript stay in Library, with source/Run links in the composer.
Cancel or navigation stops the owned job; a late acknowledgement is also canceled.
Retry reuses the saved recording and protects against duplicate network submissions.

Microphone capture requires HTTPS or localhost. On plain HTTP LAN, use the audio
file option; browsers cannot grant microphone access there. Review recognition
before pressing Send. See the [dictation contract](plans/prompt-translation-and-dictation.md).

Chat/Work's attachment tools include **Record audio** for Auto, Understand a
recording and Transcribe recording. Browser microphone permission is requested
only after that click. Finish stops the microphone and attaches a preview; it
never submits the conversation. Write the question and press Send. Cancel and
leaving the composer release the device without uploading unfinished audio.

Capture uses browser MediaRecorder (Opus WebM/Ogg, or M4A when supported), with
a 64 kbps request, a 20 MiB byte cap and automatic finish at 295 seconds, before
the native five-minute limit. No supported format or denied permission shows an
explanation and keeps file upload available. A failed attachment retains the
recorded File in memory for Retry; Cancel or leaving the page discards that local
copy. Capture is not persisted across a page reload.

Recording controls remain outside the disabled attachment fieldset so Finish and
Cancel work while other controls and Send are busy. The captured audio uses the
existing transcription upload validator and Library artifact storage. Only Send
creates the normal Task → transcription → response Runs described in
[recording questions](conversational-audio-analysis.md). Speech/portrait voice
references retain their WAV contract and do not expose compressed capture.

Normal tests cover device permission, finish, cancel/late permission, unmount,
byte and time bounds, retry of the same File and the busy composer integration.
Browser acceptance uses real Chromium MediaRecorder fed the approved sample WAV
through Chromium's fake microphone, followed by actual native CPU transcription.
It does not claim a physical microphone, Safari or mobile-device capture test.
