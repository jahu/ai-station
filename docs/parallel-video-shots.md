# Independent video shots and truthful concurrent progress

Shot-mode video currently adds the same previous-segment dependency as continuous
video, both at creation and resume. Independent shots cannot use free GPUs even
when the existing resource scheduler would admit them.

## Delivery

Only continuous video/avatar windows depend on preceding motion. Publish shot
segments independently; composition still depends on every selected successful
shot and preserves timeline order, seeds, hashes and frame checks. Resume retains
successful independent shots after gaps, queues only missing attempts, and applies
no inter-shot dependency. Preserve the Task Stop/receipt/lease contracts.

Do not weaken GPU ownership or conservative host RAM admission. Dynamic devices
and actual reservations decide concurrency; a one-GPU/low-RAM host stays serial.
Do not reduce profile RAM estimates without measurements. The present installed
Wan profile advertises 15811 MiB/shot, so concurrent generation on the current
32 GB host is not assumed or advertised as hardware-qualified.

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
