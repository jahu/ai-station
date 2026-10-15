# Local Coding: using larger source context

The owned 27B runtime is qualified at 131072 tokens, but selected source currently
stops at 32000 bytes per file / 64000 combined. This blocks ordinary larger
components and underuses the local model. PR #317 already separated cumulative
review from inference and fixed continuation after builds.

## Implementation contract

Only native Local AI opts into a bounded larger source policy: ten files,
256000 bytes per file and 256000 combined. Other providers retain ten files /
32000 each / 64000 combined. Paths, hashes, UTF-8, no links/credentials, owned
worktree locks, permissions, cancellation and recovery remain shared.

Local proposals use unique snippet replacements to edit existing large files;
whole-file output/new files retain the 32000-byte bound, response JSON stays
bounded, and resulting local selected source stays within 256000 combined.
Full snapshots are hash checked before writes. The local proposal transport is
bounded at 350000 bytes including task, guidance, source and references. Bytes
are not tokens; provider context exhaustion still fails without applying edits.

Local exploration may inspect a bounded line window (start_line/max_lines) and
search larger source files. Each read observation is bounded; finish captures
full bounded snapshots for the actual local proposal. External exploration and
context do not gain this policy. Cumulative review uses PR #317 preflight.

Normal fake-inference tests must cover large-file snippet edit, context serialization,
selection/proposal aggregate limits, immutable hashes and unchanged external
contracts. Run full checks; review a PR to develop. Reuse the owned QA task only
if real acceptance needs new evidence; do not generate another site unnecessarily.

Large proposals use separate private text-only `coding/completions` routes for
configured local servers and owned llama.cpp. Those routes accept one bounded
user message with JSON output, reuse existing forwarding/cancellation/identity
checks and do not relax ordinary Chat or vision limits. Local review records
source file count, bytes and policy.

## Acceptance case

Normal integration edits a >100 KB disposable source file using fake inference,
runs configured checks and commits the reviewed result while preserving the
original checkout/index. Typed route tests exercise actual Runner API validation
and fake upstream forwarding for configured and owned runtimes. External source
discovery keeps its empty bootstrap context; the final source selection remains
validated. Full checks are required after that compatibility fix.

Post-deployment opt-in acceptance will reuse the owned QA Work task and a new
controlled synthetic text fixture of >100 KB, edit one marker locally, run normal
Node tests/build and inspect the result at desktop/mobile sizes. The fixture has
long harmless whitespace to qualify source transport/editing without repeating
the already-qualified 110029-token GPU stress test. Do not describe it as a
complex real-code or long-context reasoning benchmark. Evidence is stored under
`data/acceptance/local-coding-source-context-20261015`.

## Delivered acceptance — PR #318

Merged as `dc13440`, deployed, and verified against the exact reviewed image.
Full corrected checks passed: 1547 backend/Runner tests, five explicit opt-in
skips, Ruff, Docker and both Compose configurations. Native source and all
original database IDs were verified after restart. The same production Work task
and owned 27B runtime completed a unique snippet edit of a 110037-byte synthetic
source file through the new Coding bridge; original checkout/index, other source,
lockfile and 1864 prior scratch files were unchanged. Node tests and Vite build
passed, a new build ZIP was saved, receipt replay created no duplicate, and
desktop/mobile browser acceptance passed. This is transport/edit/workflow
qualification, separate from the already recorded long-context reasoning tests.
Evidence: `data/acceptance/local-coding-source-context-20261015/review.json`.
