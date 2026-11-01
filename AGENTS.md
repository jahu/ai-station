# AI Station contributor guidance

The 2026-10-25 product decision in `docs/plans/unified-assistant-chat.md` removes
the user-facing Chat/Work split. Deliver one conversation; the orchestrator chooses
direct replies versus applicable tools/workflows. Preserve scoped permissions,
approvals, history and legacy API compatibility; do not add new mode switches.

Product priorities follow `docs/plans/agent-first-product.md` (user decision, 2026-10-15): focus on useful persistent agents with local code execution; defer standalone IDE/Coding expansion and further Cursor/Codex integration work. Reuse and preserve existing coding services, projects and records.

Read `docs/architecture.md`, `docs/security-model.md`, and `README.md` before changing execution boundaries.

- Preserve the modular monolith: Docker control plane, native user-level Host Runner, typed HTTP over a private Unix socket.
- All workloads use Task → Run → Events → Artifacts. HTTP handlers enqueue; workers execute.
- Keep app-owned paths relative to the data root. Validate canonical host paths and symlink boundaries.
- Never expose arbitrary commands, Docker control, or unrestricted host mounts. Never modify external runtimes, models, drivers, or `reference/photo_pipe.py` to make tests pass.
- New schema changes require Alembic migrations. Use temporary databases and fake executors in normal tests; expensive integrations must be explicitly opted in.
- Treat unfinished adapters as unavailable until their permissions, cancellation, and recovery contracts are tested. Do not report unexecuted smoke tests as successful.
- Work on feature/fix branches. PRs target `develop`; review the full diff and pass validation before squash merging. Hosted Actions are currently manual because the user has exhausted free credits and explicitly authorized local verification instead (2026-09-28). Run `./scripts/check-all.sh` or document equivalent successful local checks for the reviewed head; do not treat actual test failures as waived. Never push or merge to `main` or `master`.
- Run `./scripts/check.sh` for backend/runner changes; frontend changes also require lint, typecheck, and a production build. Validate Compose and the Docker image when deployment files change.
- The optional owner-dispatched `macos-native-checks` workflow operation is restricted to PUBLIC repositories and fixed standard free Mac labels. It does not re-enable automatic CI or paid/private/larger runners. Native test failures remain failures; hosted kernel/import evidence does not qualify Docker Desktop, Metal inference or the consumer installer.
- Keep startup instructions and implementation status accurate. Preserve existing work and make focused changes.
- Only the human owner @jahu may approve and merge PRs into `master`. Agents prepare reviewed release PRs and wait; authenticating as @jahu is not human approval. See `docs/release-policy.md`.
- Prepare `develop` → `master` PRs as `github-actions[bot]` with `gh workflow run ci.yml --ref develop -f operation=release-pr`; do not create them with the owner's CLI identity, which cannot self-approve. Review and validation precede dispatch.
- External contributions require the separately signed commercial-relicensing permission described in `CONTRIBUTING.md` before merge. A PR or DCO sign-off alone is insufficient.
