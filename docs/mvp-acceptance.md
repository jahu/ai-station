# Local MVP acceptance — 2026-09-27

The first local MVP is available for use on this workstation. The tested paths cover startup, dashboard, local Chat, images, Runs, Projects, bounded Cursor coding, self-development, agents, memory, models and diagnostics. This does not mean every capability in the broader product specification is implemented. The coding and media limits below remain explicit.

## Verification

- Python lint/format and 293 backend/runner tests passed. Frontend format/lint/TypeScript, 23 component tests and production build passed. GitHub Python, frontend and Docker checks passed for the reviewed implementation PRs.
- Both Compose configurations validate and the production image builds. A fresh disposable Docker deployment passed UI/API, native UDS telemetry, worker execution with a fake executor, SSE, API restart persistence, browser/mobile checks and owned shutdown cleanup.
- Real local `qwen3:8b` Chat and a scoped-memory agent report passed through Docker → private Runner socket → existing loopback Ollama. Chat attachment orchestration, regeneration, summaries and cancellation use fake-provider browser coverage; no real attachment inference quality claim is made.
- All six actual image cases passed at small smoke-test settings: Qwen generation, Edit, Recompose with one and multiple references, Upscale and Juggernaut generation. These are integration checks, not image quality benchmarks.
- Real external Cursor passed a disposable-repository browser task: fresh worktree, selected-file edits, diff/JSON review artifacts and native sandbox validation. Cancellation/failure/recovery boundaries use normal fake-provider regressions.
- Real native sandbox tests verify multiple commands, commands after a failed check, cancellation/timeouts, workspace write boundaries, read-only Git metadata and denied network/outside writes.
- The final read-only model scan observed 18 existing model files; runtime observation recorded three instances. Diagnostics detected two GPUs, Docker/Compose, NVIDIA Container Toolkit, the configured photo pipeline/Python/sd-cli, Git/GitHub CLI, Cursor and the existing compatible model endpoint. Codex CLI installation was detected, but its coding adapter is unavailable; Claude Code was not found.

## Self-development evidence

AI Station is registered as a Project. A real Cursor task targeted only `docs/self-development-example.md` in a fresh application-owned worktree. Its exact text hash, diff/JSON artifacts and both saved Python syntax-check commands passed. The original checkout HEAD, status and Git index hash were identical before and after. The proposed document remains in the owned worktree for review; it was not committed, merged or deployed.

The task was documentation-only. Its validation commands are syntax checks, not a replacement for the full Python/frontend release checks above. More substantial future self-development tasks need corresponding worktree-local dependencies and project validation commands.

The first attempt remains in history as a failed validation: it exposed a missing final newline and a consumed sandbox policy file. The corrected repeat passed; the failed attempt was not relabeled or removed. The external transmission of repository guidance for this test was explicitly approved by the user.

## Daily use and persistence

Open `http://127.0.0.1:8765`. The workstation's ignored `.env` contains verified paths and points to the existing preview data. From the repository, `./scripts/start.sh` builds/starts AI Station; `./scripts/start.sh --no-build` reuses a built image. The supervisor runs in the foreground; Ctrl+C stops only the deployment it owns. An already-running deployment is not taken over by a second launcher.

The running preview is pinned to reviewed implementation commit `3926405` in a separate checkout. Its SQLite backup was verified before upgrade, and previous release checkouts/data backups were retained. The API, native Runner, worker and scheduler are healthy. The private model endpoint and external photo pipeline remain independent services.

No release branch, NVIDIA/CUDA configuration, existing model file, unrelated runtime/container or original photo pipeline was modified.

## Current limits

- Coding uses Cursor with an explicit external-AI grant and up to ten selected UTF-8 files. It does not autonomously explore a whole repository, edit binaries/delete files, or commit/push/create PRs. Applied edits still require human review; validation has its own outcome. Codex, Claude Code and local coding adapters remain unavailable.
- The installed Codex sandbox failed its native probe; no OS security policy was weakened. CLI presence is not execution readiness.
- Saved validation has no network and sees only its owned worktree plus allowed system/runtime paths. Full project test/build dependencies must be prepared there. The registered AI Station example currently has Python syntax checks; these do not certify arbitrary future changes.
- Chat supports one configured local compatible provider and bounded text attachments. Vision/PDF attachments, cloud Chat and coding modes within Chat are not enabled.
- Agents can use the implemented local telemetry and own-scope memory tools. Autonomous web/email/browser integrations, remote nodes, general video/music adapters and LAN exposure remain future work. An operator password hash can be stored; it does not open a LAN listener.
- The frontend bundle-size advisory and TestClient dependency deprecation remain non-blocking development warnings.

See [verification history](verification.md) for test details and [acceptance status](mvp-status.md) for the capability ledger.
