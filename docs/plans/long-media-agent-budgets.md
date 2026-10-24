# Reviewed agent budgets for long local media

A real qualified 60-second Wan draft took 5531.9 seconds on this workstation
(`data/acceptance/long-media-20261014/real-result.json`). The persisted Agent
schema/editor and native owned-process admission currently cap the *whole*
workflow at 3600 seconds. Independent GPU/RAM admission is functioning, but even
sufficient memory cannot make that measured film fit this time limit.

Raise the explicit reviewed agent budget ceiling to four hours (14400 seconds),
consistently for saved definitions, disabled AI-assisted proposals, both editors
and private native deadline admission. Keep one uniform agent limit instead of
introducing a media-specific execution engine or ad hoc child deadline renewal.
Existing saved/default budgets do not change. Editing a time budget is an explicit
operator action; a draft still requires review/activation. A longer budget does
not grant tools, external AI, filesystem roots or more CPU/RAM/GPU.

Preserve the original absolute expiry through preparation, generated speech,
planning, every video/avatar window and final composition. Idempotent replay,
retry/resume within the workflow, resource waiting and native restart cannot
extend it. Expiry still cancels only the owned group even without a worker.
Existing per-command/sandbox and single video/music invocation timeouts remain;
public media forms cannot supply a private absolute deadline.

Replace seconds-only happy-path controls with a shared small time selector:
10 minutes, 30 minutes, one, two or four hours, plus an exact custom value for
existing/nonstandard budgets. No automatic budget increase when opening/saving
other settings. Explain that the budget includes resource waiting and all stages,
and is independent of output playback duration.

Normal verification uses disposable databases, fake installed media profiles,
real short-lived CPU-owned processes, unchanged absolute deadlines across children,
Stop/restart/replay, and an API-save/duplicate round trip of a multi-hour definition.
Compiled desktop/phone checks cover both editors and unchanged numeric persistence.
Full local review/checks, image/Compose qualification and coordinated native/source
rollout are required. No new model downloads or long GPU re-generation are needed
for this budget contract. Real agent video/avatar output remains separately
unqualified while available RAM is below its unchanged conservative reservation.
