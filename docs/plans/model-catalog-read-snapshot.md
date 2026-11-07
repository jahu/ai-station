# Model-catalog reads must not reserve SQLite's writer

Real demo-account Chat navigation produced HTTP 500 responses from provider,
lineage and preference requests. Native video playback and generation were not
the cause. The errors were `SQLITE_BUSY` at `BEGIN IMMEDIATE`.

A read-only `/proc/locks` trace of the application-owned SQLite WAL shared-memory
file correlated a 4.723-second API writer reservation with the model-catalog
request. Other requests exhausted the five-second busy window while this metadata
projection and following requests competed for the same writer.

## Repair

Keep `BEGIN IMMEDIATE` as the default for claims, leases, authorization updates,
resource reservations, scheduling and every ordinary application transaction.
After its short built-in-provider setup transaction, model-catalog rendering
explicitly enters a fresh SELECT-only projection transaction. On SQLite this
uses a deferred WAL snapshot, which permits independent writers while preserving
a consistent metadata view. A connection execution option belongs only to that
transaction; it is not a client parameter or additional filesystem/SQL capability.

Reject ORM, bulk and raw writes in projection mode before SQL execution. Starting
projection mode inside an existing transaction is refused, rather than committing
someone else's pending changes. Subsequent ordinary transactions retain writer
reservation. All owner/registry visibility checks remain in the same scoped ORM
session. No global timeout increase, retry loop, schema migration or alteration
of account permissions is introduced.

## Verification

The API regression attempts an independent SQLite write during actual catalog
rendering: it fails with `database is locked` before this repair. Additional
tests verify a consistent old snapshot after an independent commit, restoration
of normal writer reservation, rejection of three write paths and refusal of an
already-active transaction, plus refusal to change a caller-owned Connection.

`./scripts/check.sh` with ten affected catalog/account/worker/claiming/HTTP modules
selected through `PYTEST_ADDOPTS` passed 187 tests, plus global Ruff lint and format
checks. Real demo navigation and a fresh WAL-lock trace remain deployment gates.
