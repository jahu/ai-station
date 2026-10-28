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
upstream defect. Those three candidates do not pass both appearance and continuity requirements.

Keep all negative evidence. The five-window diagnostics intentionally cancel the
remaining job after collecting comparable output; they are not full-duration
qualification. Next inspect how original portrait/appearance conditioning and
temporal motion can remain separate, using exact installed source. Require a
viable seam comparison before another complete generation. Evidence:
`data/acceptance/echo-continuation-quality-20261026/` (decode-context-probe,
guidance-2, pixel-prefix and portrait-prefix). No live defaults or upstream files
have changed.

## Integration shape if end anchoring passes

The next private diagnostic keeps the existing raw temporal prefix and adds the
original portrait as the upstream inpainting end-image only on continuation
windows. The first window, speech bytes, timing, seeds, steps, CFG and memory
scope remain controlled. The installed inference function already supports this
separate end-image condition; the project-owned diagnostic wrapper uses it
without editing upstream files. It is an experiment, not an available profile.

If both appearance and exact seams improve, implement a fixed, typed appearance
recipe in AI Station's native wrapper. Freeze its version and implementation/model
observations in the full media plan, all child requests, artifact provenance and
retry identity. Keep omitted old values on the original behavior and preserve
legacy serialization/hashes, saved plans, in-flight Runs and agent snapshots.
Do not reinterpret an old plan against a newly recommended profile on resume.

Only new jobs may select a qualified recommendation from capabilities. Use the
same recipe for manual and agent full-avatar jobs. Keep the existing original
portrait hash, complete audio, owned motion checkpoint validation, process
ownership, memory budget, permissions, cancellation and recovery. An unavailable
recipe fails with an actionable error rather than silently mixing conditions.
No user-supplied CLI arguments, Python hooks, arbitrary graphs or new Chat/Work
mode may be introduced. Qualify a complete same-input narration/avatar before
promoting the recommendation; shorter diagnostic output cannot satisfy that gate.

## Viable diagnostic and product implementation under qualification

The original-end-image plus cached-motion diagnostic completed all 14 native
windows, 36.52 seconds and 913 frames. Ordinary same-Task resume reused the first
five completed clips/checkpoints without changing their bytes or execution times.
The first resume was refused while an owned cancellation lease was still active;
its failed receipt is retained. Ordinary expired-lease recovery inspected the gone
process before the accepted resume. No GPU work was blindly repeated.

All 13 sampled joins and periodic frames retain motion while substantially reducing
the baseline's progressive red/magenta appearance. Residual contrast/facial detail
changes remain. Complete final audio has correlation 0.999038 with canonical speech,
zero lag and full overlap. Actual compiled 1440/390 playback passes. This is one
controlled portrait/voice, not exact identity or phoneme synchronization. The
private engineering wrapper is not the public product recipe qualification.
Evidence: `end-anchor-prefix/full-result.json`, `full-visual-review.json`,
`full-decode-and-audio.json` and `release-player-result.json` in the investigation
folder. The full narration was reused from its already-qualified WAV; Chatterbox
was not rerun for these controlled comparisons.

The product candidate freezes `portrait_anchor_v1` and its opaque source/model
observation in new full-avatar plans, child Runs and artifact provenance. New
agent workflows freeze the recipe at enqueue; old queued snapshots without it
remain legacy. Workflow retry preserves that snapshot. Legacy public request
serialization and checkpoint identities remain unchanged. Existing jobs do not
follow a new recommendation on Resume. A changed recipe is rejected before
native dispatch or model import, and incompatible preceding motion is refused.
The implementation adds fixed typed metadata/arguments, not a shell/graph API.
Full local qualification and an actual complete public-product-source workflow
remain required before merge/promotion/deployment.

## Qualified product recipe

Frozen executable source `d2ae81c5a592495dae9fa1bb586cbf784c2b2bb3` passed
all 4,224 normal Python/Runner cases: 4,215 passed and nine explicit opt-in
integrations skipped, with Ruff/format clean. The unchanged frontend retains
PR #455's 847-test qualification. Exact backend/compiled assets in the Docker
image, all Compose variants and isolated fake API/engine/SQL/SSE/reopen pass.

The actual ordinary public API, worker and native Runner generated all 14 windows
and composed a 36.52-second/913-frame film. All native recipe observations and
motion checkpoint identities match the frozen plan. Every decoded pixel and the
complete MP4 bytes equal the controlled engineering output already reviewed
throughout and at all 13 joins. Independent full audio/decode and compiled
1440/390 playback pass. The already-qualified canonical narration WAV was reused;
this comparison did not rerun Chatterbox or prove universal identity/lip-sync.

The GPU helper's inherited footer referenced an obsolete checker filename after
successful output/cleanup, so that process exited nonzero. Its exact source and
log are retained. The independent observer actually executed both correctly named
checks successfully; the readonly final verifier reconciles all 15 successful
Runs, hashes and receipts. No GPU output was regenerated and no predicate was
waived. Details: `typed-qualification/postcheck-resolution.json` and
`typed-qualification/qualification-complete.json` in the investigation folder.

Catalog v13 adds AVATAR-005 (160 Polish cases/21 areas); all 12 offline exporter
checks pass. Owner answers remain **Nie testowano**. Code review, merge and the
backup/deployment receipts determine rollout; this is not whole-platform or
final operator acceptance.

## Operator acceptance, 2026-10-28

The operator reports progressive facial deformation, particularly the eyes, in
the full QA avatar. Record AVATAR-005 as failed (QA-020), retaining earlier
technical qualification and color improvements as historical evidence. Those
results do not prove final facial stability. The portrait end anchor is already
active; proposing it again is not a new correction. Evaluate the model's quality
ceiling as well as recursive continuation; see the
[controlled model comparison](avatar-model-quality-evaluation.md). No additional
recipe or replacement engine is qualified by that plan alone.
