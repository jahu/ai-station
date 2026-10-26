# Echo continuation appearance quality

Investigation, 2026-10-26. The complete speech fix is deployed at
`7ac543d82d6952bec6dc5cd5a660a684419cdf06`. Its actual 36.52-second,
913-frame, 14-window avatar retains the complete narration and smooth sampled
joins, but progressively increases saturation and changes facial appearance.
Preserve that adverse quality observation; do not equate decode/playback success
with appearance stability. Evidence: `data/acceptance/complete-long-speech-20261026/`.

## Establish the cause before changing the profile

1. Inspect existing frames and immutable motion checkpoints. The installed Echo
   saver applies LAB color transfer to each window using that window's first
   generated frame, rather than the original portrait. Compare its moving color
   reference with a fixed portrait reference using existing output only. This is
   an offline diagnostic, not a fresh executor or end-to-end qualification.
2. Independently decode saved VAE motion in the installed bf16 configuration.
   Start with the initial window as a control; account for upstream color transfer
   and H.264 compression when comparing published pixels. Compare standalone
   saved motion with the actual previous-history-plus-current decode, especially
   the final 17 conditioning frames. Do not assume a decoder-boundary defect from
   the earlier Wan investigation without measuring Echo itself.
3. Retain model, source, input and output observations. Diagnostics read existing
   files, write only project-owned evidence, use no downloads or full generation,
   and yield to operator workloads. Never alter installed upstream sources or
   weights, the running checkout, private operator data or original evidence.

## Candidate requirements

Choose the correction from measured evidence. If a fixed portrait color reference
is justified, use a fixed bounded native implementation; expose at most a typed
appearance profile, never arbitrary processing code, graphs or commands. Keep
legacy saved jobs and checkpoints reproducible. Freeze new profile/implementation
observations in the ordinary media plan and propagate them through agent/manual
Runs, retries, cancellation, recovery and artifact metadata. Preserve the original
portrait, audio, exact duration, motion lineage and latent tensor bounds.

Keep user controls understandable, with portrait and speech prominent. A quality
choice must describe its visible effect. Do not add a Chat/Work distinction or
technical mode. Advertise a new profile only after its contracts are tested.

## Acceptance

Cover permissions, path/hash boundaries, profile compatibility, old-plan resume,
Stop and failure behavior with fakes. Inspect an offline comparison before any
expensive generation. Qualify the actual corrected normal speech/avatar workflow
at the same or longer complete duration, with full frame/audio checks, throughout
and seam samples, original source preservation and actual desktop/phone playback.
Compare appearance against the original portrait and the retained adverse result;
do not silently trade color drift for join jumps or hide defects with a shorter
test. Run appropriate full local gates, review a PR to develop and deploy only a
satisfactory result. Exact lip-sync and universal identity guarantees remain
unproved unless separately tested; whole-platform completion remains open.

## Controlled findings (2026-10-26)

The installed VAE-only replay agrees with published initial pixels after accounting
for the upstream color transfer and two H.264 encodes. Correct temporal-history
versus standalone checkpoint decode differs by approximately 0.0003–0.0005 mean
normalized RGB in the final 17 frames. This does not support a large VAE boundary
fault as the main cause; do not import the Wan correction without Echo evidence.

The actual same-input 14-window audio-CFG-2 candidate still develops red skin and
magenta lips. Pixel-only continuation at the original CFG 3 reduces saturation
but progressively blurs and broadens the face across five windows. Independent
original-portrait windows retain appearance better across five windows, but reset
eye, mouth and head state at joins; all four exact composition joins have larger
face-crop RGB discontinuities than baseline. These controlled ablations implicate
recursive temporal conditioning in the visible drift, without proving a single
upstream defect. No candidate passes both appearance and continuity requirements.

Keep all negative evidence. The five-window diagnostics intentionally cancel the
remaining job after collecting comparable output; they are not full-duration
qualification. Next inspect how original portrait/appearance conditioning and
temporal motion can remain separate, using exact installed source. Require a
viable seam comparison before another complete generation. Evidence:
`data/acceptance/echo-continuation-quality-20261026/` (decode-context-probe,
guidance-2, pixel-prefix and portrait-prefix). No live defaults or upstream files
have changed.
