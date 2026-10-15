# Recording in the conversation composer

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
