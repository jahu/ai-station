# Common generation progress and estimates (NR-02)

Reuse HostMediaExecutor inspection, persisted Run metadata/events and the existing
MediaJob graph. Do not change native model arguments, add a queue or install a
runtime to obtain progress. All progress is observational: neither a log nor a
100% sampler can authorize successful publication.

The installed image/Wan/Echo logs contain bounded sampler counters; Krea/Wan also
emit fixed stage labels. Parse only recognized sampler formats whose total equals
the frozen request's steps, excluding weight-loading byte counters. ACE-Step's
owned preset has eight steps. Long speech's owned wrapper emits completed chunk
counters; its 1,000-token stopping ceiling is not a completion denominator. Sonic
retains its existing verified global-window observations and animation estimate.

Persist changed observations with a timestamp, stage and actual units. Deduplicate
repeated lines, keep bounded split-line buffers only in worker memory and reject
regressing/invalid counters. Recovery replays the owned logs from offset zero;
raw log fragments never become Run metadata. Terminal elapsed time uses the saved
finish timestamp, so it does not keep increasing after completion.
Use observed step speed for a labelled sampling-only remaining range; hide stale
estimates instead of counting down a stalled process. Decoding, saving and output
verification remain separate indeterminate stages.

At native dispatch, save a timing profile of executor/backend/model snapshot,
geometry, duration, inference/memory profile, reference count, text-size bucket
and actual physical device snapshot. After at least three successful comparable
owned jobs, retain a conservative observed duration range. Samples never cross
users, failed attempts or unlike profiles. This is a similar-job estimate, not a
guarantee that an external runtime's unchanged path contains unchanged weights.
No hardware-specific benchmark constant is used as the user's ETA.

One shared UI shows the actual active child, progress units, elapsed time and
estimate scope in creative history, direct media results and Run details. It
retains queue/resource waits, approvals and whole-Task Stop. A workflow's completed
stages are labelled as stages; they are not a time-weighted completion percentage.
Existing full-film and whole-avatar progress remains available.

Qualify parsers with actual observed numeric log formats and malformed/split/ANSI
cases; test persistence/staleness, profile matching and private-owner denial.
Exercise the real fake-native worker and compiled desktop/mobile UI before
rollout. Real model quality is unchanged and is not requalified by synthetic work.

The implemented candidate passes a complete 5,121-case Python/Runner baseline
(5,112 passed, nine opt-in skips), followed by 98 complete changed-family checks
after the final buffer/privacy and elapsed-time fixes. The complete 945-case UI
baseline and final 74-case changed families pass, with lint/types/format/build,
Docker and Compose checks. Compiled desktop/mobile checks use a real private API
and separate synthetic worker: measured progress/ETA, exact-source editing,
navigation/reload, Task-wide Stop, fixed terminal elapsed time and foreign-user
denial pass. Read-only parsing also recognizes numeric/stage formats from recorded
local image/Wan/Echo/speech/music jobs; this does not claim new real inference.
Private evidence: `data/acceptance/generation-progress-20261030/`.
PR #516 was reviewed, squash merged to develop and deployed on the workstation.
A fresh backup and full existing-table comparison preserved the 0039 database;
the native Runner, private access and loaded models were not restarted. Actual
production desktop/mobile account UI checks passed with a temporary audited
device that was revoked afterward. Real model quality remains a separate gate.
