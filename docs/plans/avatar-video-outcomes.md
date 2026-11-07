# Talking-avatar videos fulfill video outcomes

A real demonstration on 2026-11-07 produced its requested studio image and Sonic
speaking-avatar video. Both tools succeeded and the movie used the actual image
result and supplied recording. The final planner nevertheless exhausted its
decision validation and asked for clarification.

The independently inferred outcome called the talking film a `video`.
`missing_outcomes` counted `avatar.animate` only as `avatar`, even though its
verified artifact type is `video`. This incorrectly left a video outstanding and
rejected a truthful finish. This is fulfillment accounting, not a reason to
change the user's prompt or classify subject words.

## Repair

Treat successful talking-avatar videos as a subtype of video. Reserve outputs
for explicitly requested avatars before assigning any remaining avatar outputs
to general video outcomes. A single output never satisfies two separately
requested deliverables; a regular video cannot satisfy an explicit avatar.
Failed/running work and outputs without a video artifact remain insufficient.
The rule is independent of outcome order, prompt language and subject.

No schema, permission, resource, cancellation, retry or execution boundary changes.
No fallback installs or additional model calls are introduced. Existing model
decision records remain historical evidence; the change does not automatically
rewrite previous conversations or re-execute completed media generation.

## Verification

The regression table failed three cases before the repair, including the exact
video-request/avatar-output mismatch. It also covers order independence, separate
video plus avatar requests, insufficient counts, regular-video specificity and
failed/running/non-video outputs. The normal API → worker → native fake movie →
observation → final-answer regression failed for `video` before the repair and
passes for both `video` and `avatar` afterward, executing exactly one avatar job.

`./scripts/check.sh` with the ten affected controller/ReAct/whole-avatar modules
selected through `PYTEST_ADDOPTS` passed 130 tests, plus global Ruff lint and format
checks. The Docker image built successfully. A read-only replay of the real
completed image/avatar observations now leaves no missing video outcome. This
is not a claim of another real GPU generation after the code change.
