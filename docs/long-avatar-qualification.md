# Longer avatar qualification

PR #321 is merged/deployed as `3783ba6`. Both reliability fixes passed 1567
backend/Runner tests (five opt-in skips), lint/format, Docker/Compose and actual
desktop/mobile persistence inspection. The source-matching native service and
the same 27B/131072-context container were verified after deployment. Evidence:
`data/acceptance/runner-source-compatibility-20261015/review.json`.

## Acceptance protocol

This protocol was executed successfully on 2026-10-15; see [the result below](#executed-2026-10-15).
It targets a real 30-second avatar at the normal 384-pixel/eight-step profile.
Before this run, real evidence qualified approximately 14 seconds at 256 pixels/
four steps. The complete API → worker → native → composition result, independent
decode and browser evidence distinguish this qualification from that earlier test.

Use the existing generated QA portrait and speech, without an external provider,
new model download or modification of existing source artifacts. Prepare a
30-second PCM input from two complete copies of the existing generated speech
and a silent tail. Record this fixture construction explicitly: it tests full
duration and joins, not distinct new narration or general lip-sync accuracy.

Publish one durable job with a saved request receipt. Existing resource admission
and owned idle-model eviction apply; never terminate an external service or an
active consumer. Inspect progress through normal API/UI. Bound the test, cancel
only its own Task on timeout, preserve failed evidence, and restore the previous
owned model preset when the station is otherwise idle.

Require verified final metadata, 750 decoded video frames at 25 fps, intact
720000-sample canonical audio at 24 kHz and correctly timed encoded audio, complete timestamps, source lineage, released
reservations and desktop/mobile playback. Inspect frames around every join and
near the beginning/end. Record visual findings separately from mechanical
success. No 60-second, other portrait, higher-resolution or simultaneous-GPU
quality claim follows from this one test.

## Executed 2026-10-15

The production job completed all twelve native windows and CPU composition at
384 pixels/eight steps. Actual elapsed time was 2104.17 seconds (about 35 minutes).
The final MP4 passed independent FFmpeg and PyAV full decode: 750 frames at 25 fps,
exact timestamps, 30.0 seconds of 48 kHz AAC (1440000 decoded samples), and the
original 720000-sample/24 kHz canonical source accounting.

Contact sheets cover all eleven joins, the beginning/middle/end and the source.
No black segment or abrupt sampled join was observed. Gradual appearance/lighting
drift and hand artifacts remain visible with this full-body QA input; mechanical
success and inspected continuity do not certify lip-sync/identity quality for
every portrait. A dedicated close-up quality test and 60-second qualification
remain separate. The input repeats two complete existing generated speech clips
with a silent tail; it is not newly generated distinct narration.

Actual browser acceptance played the complete video on desktop and checked the
final seek/playback on mobile, with no page/API errors, writes or overflow. The
previous owned 27B preset was restored afterward; native observation confirmed
131072 context on both selected GPUs. No external runtime/model/driver was changed.

Evidence: `data/acceptance/long-avatar-default-20261015` (result, full decode,
contact sheets, playback, sampled resources and restored-model observations).
The first local inspection helper crashed because its filename `inspect.py`
shadowed Python's standard-library module during PyAV import; renaming it fixed
the harness. That failure was not a renderer/MP4 success and is preserved in the
inspection log. The independent FFmpeg and corrected PyAV checks both passed.
