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
