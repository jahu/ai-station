# Auto uses actual long-context allocations

Browser QA found Auto advertising a 27B allocation as verified at 131072 tokens
although its recorded native observation was only 65536. It then selected that
model over a genuinely observed 100k+ 9B allocation and failed the coding guard.
Requested configuration and successful process startup do not establish actual
model context.

For the existing matching model bytes/GPU/cache/load-success scope, count only
the smaller of the requested context and a positive integer native `n_ctx` as
proven. Missing observations remain estimates and must pass the existing native
load checks before execution. Prefer a sufficient proven allocation over a
slightly larger estimate for the same candidate; retain the 100352-token floor.
Hardware discovery, explicit model choices, permission snapshots and loading
remain unchanged. Busy-model resource queueing is a separate open QA issue.

Acceptance: the read-only Auto preview must select an actually qualified local
model on this workstation; fresh unified-chat file creation and local coding
must execute with that snapshot and produce verified results. Do not alter old
runtime records or call a preview alone a successful coding/file smoke test.
