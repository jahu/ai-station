# Consistent speech volume — release 0.4.0

## Diagnosis and intended behavior

The reported latest Fish speech contains six independently synthesized PCM parts.
Their typical active-speech levels differ by roughly 13 dB. The adapter concatenates
them without level matching, and Sonic muxes the original audio unchanged. Peak
normalization of the whole file cannot correct those changes over time.

Add one model-independent, versioned CPU finishing policy for spoken audio:
bounded, smoothed local RMS gain with a silence threshold and gain ceiling,
followed by a peak limiter. Use the existing FFmpeg libraries through PyAV;
no new AI models, cloud calls, GPU allocation or host executable installation.
Preserve words, pace, pauses, audio duration and A/V alignment. Do not automatically
apply speech processing to music or sound effects.

New speech/avatar requests default to even volume, with an ordinary checkbox to
retain the raw delivery. Existing persisted Runs without that setting keep their
old behavior. Finishing stays in the worker, outside database transactions and
before the claim-fenced artifact publication. The original native result stays
intact; processed output is a separate file. A processed canonical speech source
is not compressed again when an avatar uses it. Store the versioned processing
receipt and before/after measurements in artifact metadata and emit Run events.

Library audio/video details gain an explicit "Even out voice volume" action.
It creates an ordinary container CPU Task/Run and a new derived Artifact with
source lineage. Never edit the existing artifact or resynthesize the voice/avatar.
Copy video packets without video re-encoding; encode only the processed audio.
Freeze source identity/ownership, observe cancellation and lease ownership during
work, recheck before publication, and retain ordinary recovery/retry contracts.

## Acceptance

Test real uneven speech, controlled level changes, silence, constant audio,
mono/stereo, bounded gain, clipping protection, exact PCM sample count and no
video packet changes/A/V shift. Cover source ownership, Trash/path/symlink changes,
claim fencing, Stop, failure/recovery, defaults/opt-out and inherited processing.
Repair the user's latest audio/avatar as new private Library results; report
measured differences without claiming a human listening pass. Keep private media
out of the repository and public release. Update README, UI and qualification;
build checked Linux/Windows 0.4.0 assets and use the owner-reviewed master release
workflow. No new GPU/Windows-inference qualification is implied by a CPU fix.

## Verified implementation — 2026-11-08

The worker's fixed `speech-volume-v1` profile combines soft-knee compression,
smoothed RMS gain and a peak limiter. Processing supports mono/stereo WAV speech
and MP4 voice tracks up to five minutes. Measurements are active one-second RMS
windows in dBFS, not perceived-loudness LUFS scores or a promise to remove prosody.

Two ordinary owner-scoped repair Runs completed on the reported private media in
the deployed 0.4.0 preview. The audio's active-window P90–P10 spread changed from
13.390 to 8.407 dB; the avatar's changed from 13.398 to 8.485 dB. Original file
hashes and derived-artifact lineage were checked. The avatar retained its encoded
video packets and their timestamps; its decoded audio timing stayed within two
samples. This is measured qualification, not a human listening verdict. Private
recordings and comparison files are excluded from public assets.

The built Linux application image passed real API → queued Run → CPU worker →
WAV/MP4 playback tests with neutral synthetic media. An offline 0.3.2 → 0.4.0
upgrade retained twelve populated tables and artifact bytes, passed SQLite
integrity/foreign-key checks and served the compiled UI on unchanged schema 0045.
Actual Chromium checks at 1440- and 390-pixel widths passed the Library action,
progress/Stop controls, result navigation, balanced badge and audio playback
element, with no page errors or document horizontal overflow.

Automated tests cover sample count, finite/limited gain, silence/stereo, video
packet/timestamp preservation, source hashes, idempotency, ownership, cancellation,
lost claims, source removal/symlinks and defaults/opt-out. A legacy fake-avatar
fixture now produces a valid neutral MP4 with audio instead of text masquerading
as a movie. This allows the real finishing path to run in its lifecycle tests.
Operator cases `VOICE-006` and `VOICE-007` remain unexecuted listening/comparison
checks in the QA workbook.

Release assets were built from production source `027437a16192382a39b19a80f083cddbf0fbc9ce`;
later fixture and qualification-document changes do not change shipped runtime
code. Final regression and native installer results belong in the release notes.
