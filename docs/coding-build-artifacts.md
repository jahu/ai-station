# Coding build artifacts

## Current delivery and next gap

PRs #311–313 are merged and deployed from develop `ffed73d`. New managed
projects can prepare dependencies and run detected checks automatically. Actual
Work created a project, continued after the corrected root `.gitignore` failure,
used installed RVN 27B IQ2_XS with owned two-GPU llama.cpp at 131072 context,
passed a real React rendering test and Vite production build. The built page
rendered in a fresh real browser with unrelated requests blocked. Original
checkout/index stayed unchanged. The Coding progress summary distinguishes
successful checks, untested code, install failures, approval and Stop.
Evidence: `data/acceptance/coding-gitignore-20261015` and
`data/acceptance/coding-task-progress-20261015`.

The generated build currently remains under the owned worktree. The next focused
increment exposes a downloadable build through the existing Artifact domain.
It does not run a development server or execute generated HTML in the UI.

## Implementation contract

- Reuse `project_validation` and its existing owned process/lock/cancellation
  contract. No new shell, arbitrary filesystem path or runtime operation.
- After all requested checks pass, detect only the fixed worktree-root `dist`
  directory when a successful `build` command was recorded. Other output layouts
  remain explicit unsupported states for this first increment.
- Drain verified children of the owned validation session/group before capture,
  so background helpers cannot keep writing after their parent command exits.
- Capture output while the validation wrapper still owns the worktree lock.
  Produce a ZIP in its application-owned validation output area, with a derived
  UUID filename; never include source repositories, `.git`, credentials,
  environments or `node_modules` by walking a broader root.
- Bound file count and total uncompressed bytes (initially 1000 files / 32 MiB).
  Reject symlink directories/files, hardlinks, nonregular files, traversal,
  absolute ZIP members, credential/hidden paths and redirected roots. Use
  descriptor-relative no-follow opens and verify read snapshots against changes;
  output creation must be exclusive and partial archives must not be published.
- Treat `dist` as untrusted generated data. It is never imported or executed by
  archive creation. Missing/unsupported output must not turn a passed test/build
  into fabricated exported output; report export availability/warnings separately
  from actual command results.
- Extend the typed native validation report with optional owned archive metadata
  (relative output path, size, SHA256, file count). Check request/run ownership,
  expected output prefix and content before backend artifact registration. Keep
  the old report contract valid when there is no archive.
- Register a normal `archive` Artifact with ZIP MIME, validation/source Run and
  project provenance. Emit `artifact.created` normally. Recovery must not
  duplicate export artifacts or advertise partially written ZIPs.
- Coding/Work review shows a clear Download build action and a Library link when
  the artifact exists. Keep HTML/JS as downloaded data, preserve attachment and
  nosniff delivery, and do not imply an interactive preview is implemented.

## Verification and acceptance

Normal tests use disposable owned worktrees and fake build commands. Cover ZIP
contents/hash/provenance, missing output, failing checks, bounds, symlink and
hardlink/rename escapes, concurrent mutation, Stop and old report compatibility.
Run the required backend/Runner checks, frontend checks and reviewed Docker build.

Use the already-generated QA React project for opted-in actual sandboxed
validation/export acceptance; do not spend tokens generating that website again.
Verify the ZIP and real UI download/Library flow. Preserve its original checkout
and initial failed attempt. Do not claim arbitrary web builds, music, remote
nodes or the whole product are complete from this acceptance.
