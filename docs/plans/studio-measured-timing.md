# Measured narration and an explicit edit-length policy

The real standalone two-image reel requested twelve seconds. Its complete
24-word narration required 305 frames including the existing breathing room.
The original mixer extended that first scene from 180 to 305 frames and kept
the silent closing at 180 frames: 485 frames / 16.167 seconds. Neither speech
nor source bytes were lost, but the closing could absorb the overrun.

Add an optional frozen `timing_policy` to production, audio production and mix
requests. Omission retains exact legacy serialization, fingerprints and the
current extend-only behavior. `preserve` keeps each planned hold, extending only
for complete speech. `fit` retains the saved edit's total when physically
possible, using flexible image/graphics holds. It never speeds or cuts speech.

Every scene retains at least one second. Complete speech plus the existing
400-ms cue margin is a lower bound. Planned video windows remain intact;
generated footage may expand when its actual narration requires more coverage,
while an insufficient selected Library-video window fails with an actionable
error. Unknown source types are conservative fixed holds. Shared visuals retain
their source, order, trim and independent scene timing. Excess capacity comes
only from still/graphics holds and is distributed deterministically. If all
minimums require more than the requested edit, report that actual longer edit.

Manual Studio settings expose both policies and default to preserving holds.
New assistant requests freeze the fit policy at enqueue; old controllers,
wrappers, production/audio Runs and saved revisions do not inherit it on restart.
The same pure calculation determines music coverage, queued mix inputs and worker
revalidation. Music remains independently coverage-checked; narration is always
decoded to its real end. The change creates normal Tasks/Runs and immutable
measured revisions; no migration, new executor, permissions or native operation.

Qualification requires the captured 305+180 case fitting to 305+55, legacy
identity/no-mutation tests, finite clip/shared-source bounds, rounding and
impossible-budget cases, complete PCM/score tests, privacy/recovery/Stop and
settings persistence. Actual qualification reuses the completed speech and
photographs through a new ordinary mix/export; no inference replay is needed.
Review, local checks, exact image and preserving idle rollout precede release.


## Natural narration and performance (owner feedback, 2026-11-12)

The 95.633-second educational sample was not accepted: the owner heard slow,
robotic, unexpressive delivery. Its six frozen cues all selected calm + slow.
The existing slow option applies a 0.8-rate pitch-preserving PCM time stretch,
lengthening each generated cue by 25%. Overall voice_direction was editorial
metadata, not a Fish instruction. Technical transcript/volume checks did not
qualify performance quality.

Keep Shot.narration as exact spoken words. An optional narration_segments list
stores matching ordered phrase text plus short open natural-language style
hints. Only the Fish adapter compiles these into inline [style] tags; Chatterbox
receives plain words. Joining phrases must match every spoken word (whitespace
normalization only), and compiled input must fit the existing 1000-character
speech bound. No new native endpoint, dependency, download or model is needed.
Fish supports open inline performance descriptions; see
https://fish.audio/s2/ and https://github.com/fishaudio/fish-speech.

The local director defaults to natural pace, with purposeful phrase variation.
A calm brand or educational topic does not imply slow audio processing. Explicit
whole-take direction overrides phrase hints; explicit slower/faster selection
retains its existing behavior. Studio exposes the phrase hints in shot editing;
editing words clears stale phrase mappings. The bounded word-limit rewriter
likewise drops mappings only for changed lines. Future productions freeze the
new hints; historical JSON without the optional field retains its serialization,
fingerprints and behavior. References still use their actual offline transcript,
not tagged model input. Speech word counts, captions and memory remain clean.

A real short opening using the same words and natural pace with inline hints
rendered 12.910 seconds, compared with 16.312 for the original calm/slow cue.
It used a newly sampled voice, so this does not isolate voice identity or prove
subjective quality. Independently transcribe the sample, retain both takes, and
review listening quality before calling the full film publication-ready.
