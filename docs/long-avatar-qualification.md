# Longer avatar qualification

PR #321 is merged/deployed as `3783ba6`. Both reliability fixes passed 1567
backend/Runner tests (five opt-in skips), lint/format, Docker/Compose and actual
desktop/mobile persistence inspection. The source-matching native service and
the same 27B/131072-context container were verified after deployment. Evidence:
`data/acceptance/runner-source-compatibility-20261015/review.json`.

The next acceptance increment exercises a real 30-second avatar at the normal
384-pixel/eight-step profile. Existing real evidence only qualifies approximately
14 seconds at 256 pixels/four steps. Do not claim the longer profile works until
its complete ordinary API → worker → native → composition chain succeeds.

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
720000-sample audio at 24 kHz, complete timestamps, source lineage, released
reservations and desktop/mobile playback. Inspect frames around every join and
near the beginning/end. Record visual findings separately from mechanical
success. No 60-second, other portrait, higher-resolution or simultaneous-GPU
quality claim follows from this one test.
