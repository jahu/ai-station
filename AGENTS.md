# AI Station contributor guidance

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
- Keep startup instructions and implementation status accurate. Preserve existing work and make focused changes.
