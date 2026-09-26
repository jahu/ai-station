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

The existing photo Python environment, photo pipeline, stable-diffusion.cpp executable, and image/LLM/video model roots are present. The original photo pipeline matches `reference/photo_pipe.py` and was not modified. Codex and Cursor executables are on PATH; Claude Code was not found. Open WebUI is already running in a separate Docker project and was left untouched. At that stage model-server reachability/authentication had not been verified; see the later local-provider acceptance below.

## Initial foundation limitations (superseded where noted below)

At the initial foundation checkpoint no real image generation/edit/recompose/upscale, coding agent task, or local/cloud model completion had been executed. The image adapter is enabled and verified against a Pillow-only fake pipeline in all five mode/backend combinations. Tests cover source lineage, image delivery, thumbnails, complete stdout/stderr chunks, lost dispatch responses, disconnected polling, cancellation during dispatch, permissions, unknown exit codes, retries, and the actual reference CLI parser. Local chat is enabled and verified against HTTP mock streams and a temporary loopback fake provider. Coding adapters remain unavailable; local agents were enabled in the later lifecycle slice below. No driver, CUDA, model file, existing AI script, or unrelated service was changed.

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


## Local provider acceptance — 2026-09-25

An explicit `AI_STATION_REAL_LOCAL_LLM_TESTS=1` smoke used an isolated temporary application database and the existing local endpoint `http://127.0.0.1:11434/v1`, whose model listing reported `qwen3:8b`. A normal Chat Task/Run executed through the worker and returned `AI Station local check OK.` with `max_tokens=512`, temperature 0 and `/no_think` in the prompt. The assistant response remained readable after resetting the database engine. The first attempt with only 64 output tokens failed with no report text; it was not counted as success. This verifies this local OpenAI-compatible endpoint, not a llama.cpp deployment. The endpoint at port 8080 was unavailable. No runtime was installed or reconfigured.

## Local agent lifecycle — 2026-09-25

- `./scripts/check.sh`: 225 Python tests passed, including scheduler concurrency, one-shot execution, scoped memory, permission enforcement, stale definition edits, provider failure and silent-stream cancellation.
- Frontend: 13 component tests passed; lint, TypeScript and production build passed. Existing bundle-size advisory remains.
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/ai-station-browser .venv/bin/python scripts/agents_smoke.py`: passed disabled draft/review, activation, actual worker with fake compatible provider, Markdown artifact, pause, API restart/history persistence, scoped memory navigation, duplication and mobile overflow check. Screenshots inspected locally.
- Agent inference in these tests used a fake provider. The separate real local Chat completion above is not a real agent or coding-task acceptance claim.


## External runtime observations — 2026-09-25

- Python lint/format and 231 tests passed; frontend lint/typecheck/production build and 14 component tests passed.
- `scripts/runtimes_smoke.py` passed browser → API → worker → native UDS process observation, truthful unavailable test endpoint, durable registry reload and mobile-width checks. Screenshots inspected.
- A real read-only process scan completed across 420 visible processes and recognized the existing Ollama process. No process arguments/environment were returned or persisted. This proves observation, not runtime ownership or generation readiness.
- Regression tests cover PID reuse identity, unsupported processes, output limits, partial scans, cancellation, failed refresh preserving prior data, stable registry IDs and rejected arbitrary probe/mutation requests.


## Real image acceptance — 2026-09-25

`scripts/real_images_smoke.py` requires `AI_STATION_REAL_GPU_TESTS=1` plus explicit photo Python/script paths. It uses temporary application data, the API, worker and a private native runner. The adapter enforces Hugging Face/Transformers offline mode; no weights were downloaded and the original script hash was unchanged.

With the existing models on the workstation, these actual executions passed: Qwen generation (29.8 s), Edit (29.6 s), Recompose with one reference (29.6 s), Recompose with two references (29.6 s), Upscale (12.3 s), and Juggernaut generation on the final repeat (11.4 s). Generation used 256×256 and two sampling steps; input references were synthetic color fixtures. These are integration checks, not visual-quality or realistic-workload benchmarks. Results/logs remain in `/tmp/ai-station-real-images-j_3ps729` and `/tmp/ai-station-real-images-pdeev_3y` for this development session.

The first script attempt resolved the venv interpreter symlink incorrectly and failed before inference; the script now preserves the venv path. The first two Juggernaut attempts generated output but exposed a premature interrupted status while native child reaping was pending. Those attempts are not counted as successful end-to-end Runs. The final repeat passed after the completion protocol fix; regressions cover pending reaping, resource retention and artifact registration only after confirmed exit.

Reproduce explicitly: `AI_STATION_REAL_GPU_TESTS=1 AI_STATION_PHOTO_SCRIPT=/your/photo_pipe.py AI_STATION_PHOTO_PYTHON=/your/venv/bin/python .venv/bin/python scripts/real_images_smoke.py`. The script selects a discovered GPU with at least 9000 MiB free, preserves results in a new temporary directory, and supports `--gpu`, `--modes` and `--timeout`.


## Docker access to loopback-only inference — 2026-09-25

The isolated `scripts/model_bridge_smoke.py` deployment passed actual Docker API/worker → private Runner socket → host-loopback fake provider completion and silent-stream cancellation. The direct container endpoint was deliberately unreachable. An explicit `--real` repeat with `AI_STATION_REAL_LOCAL_LLM_TESTS=1`, `AI_STATION_LLM_BASE_URL=http://127.0.0.1:11434/v1` and `AI_STATION_LLM_MODEL=qwen3:8b` returned `AI Station bridge OK.` through an ordinary Chat Run. This verifies the existing Ollama compatible endpoint from Docker without changing its bind address; it is not a llama.cpp or coding-agent test.

Both Compose configurations and the production Docker image build passed. Tests cover endpoint mismatch, rejected tools/redirects, secret filtering, upstream stream closure and client disconnect before inference response headers. The preview deployment at port 8765 was left running on its original version.


## Dashboard activity — 2026-09-26

Python lint/format and 243 tests passed; frontend lint, TypeScript, 16 component tests and production build passed. The expanded `scripts/runtimes_smoke.py` checked the Home dashboard in Chromium against a temporary database and real read-only runner telemetry. A scheduled fixture agent and an empty fixture conversation appeared, the conversation link opened the correct record, and the runtime observation report appeared among recent artifacts. No model inference or scheduled agent execution was started by this smoke. Desktop/mobile screenshots were inspected; no horizontal overflow or browser errors occurred.

API regressions verify bounded lists, total counts independent of list limits, executing Runs before queued Runs, exclusion of paused/manual schedules, overdue and stale flags, and omission of prompts from dashboard summaries. The existing bundle-size and TestClient deprecation advisories remain visible.
