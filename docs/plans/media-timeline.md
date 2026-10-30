# Saved media timeline (NR-08)

Reuse private CreativeSession workspaces with capability `timeline` and existing
CreativeTurn render history. Migration 0041 preserves existing creative data and
adds immutable TimelineRevision rows: manifest, frozen owned sources, parent,
position and idempotent save receipt. Drafts continue through the existing
versioned autosave. A reviewed render binds the exact saved revision and produces
an ordinary Task/Run/Event/Artifact, never executing inside the API handler.

A manifest contains one video lane (trim/move/reorder, gaps are black) and up to
sixteen independent WAV tracks for speech, music and effects. Video clips retain
optional original audio with gain/mute/fades. Frames are explicit source/master
indices; audio trims use source samples and master duration frames. Export is
24/25 FPS with rational timing and 48-kHz stereo. Mixed source rates/sizes are
explicitly resampled/letterboxed. Each absolute output frame/sample endpoint is
computed from its position, avoiding cumulative rounding drift. Keep every
source and previous revision/result. No arbitrary codecs, filters or commands.

Video → Edit opens the workspace, with Library insertion, numeric/keyboard and
pointer movement, trimming, track gain/mute/fades and measured waveform/playhead
views. Source playback helps choose trims. **Preview this edit** renders the
saved manifest through the same verified CPU pipeline as export; a changed draft
marks an older preview as a prior version. A verified current preview can be
exported without repeating the render. Do not imply an unrendered edit is already
encoded or play a different audio mix as the final preview.

The native owned timeline renderer validates the full frozen source bytes,
frame timing and audio bounds, uses a fixed four-GiB/zero-swap user scope,
reserves CPU load RAM and has an absolute deadline. It streams video, mixes
bounded PCM, records peak protection, encodes a temporary MP4 and verifies full
frame/sample coverage before atomic publication. GPU models remain untouched.
Owned process inspection, cancellation, lost acknowledgement and leases use the
existing HostMediaExecutor/ProcessManager. WAV waveform analysis uses a bounded
ordinary container-side Run and never publishes fake waveforms.

Private APIs, revision references, browser drafts, source files and rendering are
account-bound; administrator inspection remains explicit and read-only. Test
populated migration preservation, two-user and admin boundaries, idempotent saves
and render submissions, changed sources, rational trimming/rate conversion,
position/fade/mute/peak behavior, Stop/recovery and independent prior revisions.
Qualify a real CPU fixture mix/export and compiled desktop/mobile workflow before
rollout. The full release also retains NR-07 agent exposure/perceptual acceptance,
expressive speech and guided installers/catalog; this editor is not completion
of the whole release.
