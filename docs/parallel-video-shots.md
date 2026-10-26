# Independent video shots and truthful concurrent progress

Shot-mode video publishes independent segment Runs at creation and resume.
Available GPUs can generate separate shots concurrently when the conservative
host-memory admission also permits them. Continuous windows remain sequential.

## Delivery

Only continuous video/avatar windows depend on preceding motion. Publish shot
segments independently; composition still depends on every selected successful
shot and preserves timeline order, seeds, hashes and frame checks. Resume retains
successful independent shots after gaps, queues only missing attempts, and applies
no inter-shot dependency. Preserve the Task Stop/receipt/lease contracts.

Do not weaken GPU ownership or conservative host RAM admission. Dynamic devices
and actual reservations decide concurrency; a one-GPU/low-RAM host stays serial.
Do not reduce profile RAM estimates without measurements. The original installed
Wan profile advertises 15811 MiB/shot. The later bounded landscape profile uses
an enforced 11264-MiB scope per shot; its measured two-device acceptance is below.
This does not change admission or qualify concurrency for the original profile.

Expose running and waiting shot counts plus actual allocated GPU IDs in the shared
job projection/result, so queued/composing stages are not mislabeled as active
generation. Keep continuous progress and final-only completion unchanged.

Verify fake generation with real CPU composition, simultaneous independent workers
on distinct discovered GPU IDs, RAM/one-GPU fallback, out-of-order completion,
failed-gap resume, cancellation of all active/queued stages, receipt replay and
continuous dependency preservation. Run full backend/frontend checks and build.
Real GPU speed/parallelism requires separate measured hardware acceptance; do not
repeat the already-qualified 92-minute 60-second generation merely for this graph
change. A production graph/Stop check must pause only the idle owned worker before
publication and cancel all queued test stages before restarting it. Occupied GPUs
alone are insufficient: existing idle-model eviction may free them. This check
proves real publication/Stop without inference, not hardware parallel generation.

Out-of-order completion requires ordered final lineage as well as ordered decoded
frames. Latest partial preview follows actual completion time among selected
successful attempts, not the largest segment number. Historical failed attempts
and reused independent shot artifacts remain intact on resume.

## Delivered verification — PR #320

Merged/deployed as `37570af`. Full checks passed: 1555 backend/Runner tests,
five explicit opt-in skips, 483 UI tests, lint/format/types/build, Docker/Compose.
Private candidate production UI passed actual 1440/390 rendering with explicitly
synthetic two-device progress. Actual production graph/receipt/Stop acceptance
paused only an idle owned worker, published three independent queued shots plus
composition, verified only composition dependencies, then canceled all four before
restoring three fresh worker slots. No test generation or model eviction occurred;
the existing 27B runtime remained ready. Evidence:
`data/acceptance/parallel-video-shots-20261015/review.json`.

The next [queue fairness fix](media-resource-wait-fairness.md) prevents resource
waiting in a large shot batch from hiding new interactive CPU work.

## Actual two-GPU acceptance — 2026-10-26

Unchanged running source `81c87650f480c1ad4713d65e84e50ffe83b7e3c4`
completed the ordinary API → three-slot worker → private Runner → two independent
Wan Runs → CPU composition path in an isolated database. Two distinct owned CUDA
PIDs were observed simultaneously on the two discovered RTX 3060 devices;
20 observations include both devices at 100% utilization. Each native process
had an observed 11-GiB kernel memory limit and zero swap allowance. Neither
production data nor unrelated services were changed.

The exact profile is two two-second landscape shots, 1280×704, 20 steps, CFG 5,
seed 43, GPU Auto and `bounded_11g`. Each generated 49 frames; ordered composition
retained 48 from each for 96 frames/24 fps/four seconds, with a deliberate cut at
frame 48. The complete workflow took 478 seconds. This is a measured result,
not an equal-workload serial speedup benchmark or a promised completion time.

Both shots have no inter-shot dependency. Source hashes, ordered artifact parents,
all decoded output frames and their match to the ordered source clips pass.
Every measured health request completed in under 0.025 seconds. Actual compiled
1440px full playback and 390px ending playback pass without JavaScript errors,
horizontal overflow or workload requests. Inspected shot beginnings/endings
retain the requested landscape detail and exposure. All owned processes stopped
and no active resource reservations remained.

Evidence: `data/acceptance/parallel-wan-20261026/qualification-complete.json`,
`result.json`, `independent-output-check.json`, `release-player-result.json` and
`visual-review.json`. The local independent preview is
`data/test-previews/Filmy/04-Wan-2GPU-dwa-ujecia-4s.mp4`.
This qualifies the recorded short-shot profile; continuous motion, longer scenes,
different quality profiles and other machines retain their separate acceptance.
