# Streaming chat interrupted by activity-cookie database contention

Operator report, 2026-10-25: the two latest answers failed after partial streaming.
Saved Runs `4d19bd5c-4722-42b2-81c2-71bd65398132` and
`b8f0352c-27d1-4e01-840f-ee45e15484cb` contain 151/83 saved chat deltas and
failed with PendingRollbackError wrapping SQLite `database is locked` at BEGIN
IMMEDIATE. One used page reading, the other public search. Worker logs also show
busy database errors terminating slots and restarting their group. No prompt or
operator credentials need to be copied into release documentation.

## Root cause and correction

Once per activity-refresh interval, authenticated middleware prepared a new cookie,
then queried secure-cookie policy again after the endpoint returned its response.
The response could still own its SQLAlchemy session/SQLite writer reservation.
Opening a second session for policy reading waited on that same response. The
private policy read masked its timeout with default policy; concurrent chat delta
writes and worker claims could nevertheless time out. Normal fast endpoints or
unit tests without concurrent streaming concealed this cycle.

Freeze only the secure-cookie boolean using the existing authenticated session,
then attach the cookie without database I/O after endpoint response creation.
Preserve idle/absolute expiry, token rotation/logout precedence, HttpOnly/SameSite
and private HTTPS Secure behavior. Cookie values never enter logs or model prompts.

On a failed chat flush, rollback an invalid transaction instead of committing it
again and masking the original error. Always cancel/await pending inference and
close the generator even when persistence cleanup fails. Keep already committed
partial text inspectable; do not replay a failed response automatically.

A worker slot rolls back/closes its session and continues normal durable-state
inspection after a specifically identified SQLite BUSY/LOCKED error. Match actual
SQLite error codes, including extended codes; do not hide other database failures
or log SQL/parameters. Preserve claimed leases/recovery policy and other slots.
This is not an executor retry or a busy-timeout increase.

## Verification and release

Deterministic LAN and private-HTTPS tests fail against the exact previous auth
module and pass with the fix while an endpoint session remains held. A real ORM
flush error checks original-error preservation and saved partial text. An actual
API/worker/provider stream survives repeated authenticated history polls and
activity-cookie refreshes. Busy/other-error worker tests and the existing auth,
chat, cancellation and worker-slot cases are required. Qualify complete normal
Python/Runner gates, source-identical frontend reuse, exact image/Compose and a
bounded existing-local-model streaming/polling acceptance before review/deployment.
Do not claim user Runs recovered: keep failed history and require a new explicit
message/regeneration to repeat inference. Preserve data, auth and ready model.

Evidence: `data/acceptance/chat-cookie-db-lock-20261025`. Local qualification passes all3867 CPU cases (3858 pass/nine opt-in skips),
Ruff/format, exact image/three Compose and isolated-image fake API/worker/SQL/SSE.
Frontend806/native qualification is reused only after exact source identity. Two
actual local responses completed with435/632 saved deltas and197/293 forced
activity-cookie refreshes during streaming; max history latency139ms/43ms.
Ready container/context and production data stayed unchanged. Original failed
Runs/messages are recorded by hash for post-deployment preservation checks.
Full review and deployment require their receipts; local qualification alone
is not a deployment claim. This work takes priority over the planned
managed Memory embeddings and permanent Library deletion. The final Polish QA
workbook must cover concurrent streaming and login-session activity refresh.
