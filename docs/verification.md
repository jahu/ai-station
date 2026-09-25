# Verification record — 2026-09-24

## Automated checks

- Backend and Host Runner: 195 pytest cases passed; Ruff lint and formatting passed.
- Frontend: ESLint, strict TypeScript, eight UI behavior tests, and production build passed.
- Production Docker image and both Compose configurations validated.
- Production and development Docker deployments (including the Vite proxy): native Unix-socket telemetry, API health, worker execution through a fake executor, SSE replay, persisted history after API container restart, and supervisor cleanup passed.
- Image Docker/browser smoke: Generate → Library → Edit passed using a Pillow-only fake pipeline; source reuse and artifact rendering were checked. Artifact delivery releases database transactions before streaming. No real model inference was performed.
- Chromium: desktop dashboard, command palette navigation, run timeline, and mobile overflow checks passed with no page errors. Desktop and mobile screenshots were inspected.

- Local chat browser smoke: model discovery, streaming, Markdown/code rendering, API restart persistence, regeneration, cancellation while the provider is silent, and mobile layout passed. Screenshots were inspected. This uses a fake provider and does not prove real llama.cpp inference.

- Git inspection tests use disposable repositories: command helpers remain uninvoked, the index/configuration stay unchanged, injected options and inherited Git path overrides are rejected, metadata escapes fail, and output/time limits terminate owned subprocesses.
- Projects: 18 API integration/validation cases cover persisted registration, real Git status, canonical duplicates, root boundaries, concurrent registration, mandatory protections, stale edits, active-run guards, runner outages, and independent database writes during inspection. A Chromium smoke through the native Unix socket additionally passed registration, editing, API restart persistence, stale-editor rejection, runner outage display, and mobile layout. Screenshots were inspected; the disposable repository's index remained unchanged. No coding executor or project validation command was launched.

## Actual workstation observations

Docker Engine 29.1.3 and Compose 2.40.3 are available. Two NVIDIA GeForce RTX 3060 GPUs (12 GiB each) were enumerated by `nvidia-smi`; live metrics were read through the native runner into the containerized API. These observations are not architectural assumptions.

The existing photo Python environment, photo pipeline, stable-diffusion.cpp executable, and image/LLM/video model roots are present. The original photo pipeline matches `reference/photo_pipe.py` and was not modified. Codex and Cursor executables are on PATH; Claude Code was not found. Open WebUI is already running in a separate Docker project and was left untouched. Model-server reachability/authentication has not been verified.

## Not tested / unavailable

No real image generation/edit/recompose/upscale, coding agent task, or local/cloud model completion was executed. The image adapter is enabled and verified against a Pillow-only fake pipeline in all five mode/backend combinations. Tests cover source lineage, image delivery, thumbnails, complete stdout/stderr chunks, lost dispatch responses, disconnected polling, cancellation during dispatch, permissions, unknown exit codes, retries, and the actual reference CLI parser. Local chat is enabled and verified against HTTP mock streams and a temporary loopback fake provider. Coding/agent adapters remain unavailable. No driver, CUDA, model file, existing AI script, or unrelated service was changed.

The frontend build currently reports a bundle-size advisory; this is a local application with a 347 KiB gzip initial JavaScript bundle. The TestClient dependency emits a Starlette/httpx deprecation warning; tests pass. Neither warning is suppressed.

## Owned worktree preparation

Real Git preparation passed through the API, worker, native Unix-socket runner, and browser using a disposable repository. The generated worktree contains the selected committed base while the original checkout retains its uncommitted changes and identical index bytes. The Run records logs, ownership, and a JSON artifact. Regression tests cover request replay/conflicts, disabled checkout hooks and filters, lost dispatch responses, symlink destinations, missing bases, capability permissions, cancellation, and bounded runtime. A separate cancellation regression confirms helper Git reads remain in the managed process group. Partial or uncertain preparations are preserved for inspection; no coding CLI, validation command, push, or PR was executed by the application.

## Scoped memory workspace (2026-09-25)

- Python lint/format and 199 tests passed; frontend lint/typecheck/format/build and 10 UI tests passed.
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/ai-station-browser .venv/bin/python scripts/memory_smoke.py`: browser CRUD, reload persistence, disable/search, confirmed deletion and mobile-width checks passed against a temporary database. No model call was made.
- Full feature diff reviewed for source/scope validation, FTS filtering before limit, stale-write protection and immutable Chat context. Production CSS reviewed from desktop/mobile screenshots.

## Managed model discovery (2026-09-25)

- Python lint/format and 207 tests passed; frontend lint/typecheck/format/build and 11 UI tests passed.
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/ai-station-browser .venv/bin/python scripts/models_smoke.py`: browser → API → worker → native UDS runner → managed scan → persisted registry/artifact passed. Category filtering, reload persistence, unchanged fixture bytes/mtime, mobile width and browser errors were checked. Desktop screenshots inspected.
- Browser testing revealed a SQLite/SSE event-loop lock; blocking SSE reads now run in a thread with a private short session. A concurrency regression test and the repeated browser smoke pass.
- Real metadata-only discovery inspected the workstation's existing `~/AI/models/{llm,image,video}` roots: 18 files (4 LLM, 6 image, 8 video), totaling 86,104,602,180 bytes. No model contents were opened, loaded or modified. This verifies discovery, not inference or runtime compatibility.
- Migration upgrade/downgrade preserves pre-existing model metadata. Cancellation terminates only the owned scan process and leaves the previous inventory intact.
