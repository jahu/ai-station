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


## Conversation summaries — 2026-09-26

Python lint/format and 252 tests passed; frontend lint, TypeScript, 18 component tests and production build passed. Summary tests cover incremental coverage, scope separation, exact sources, canceled silent inference, oversized/failed output, artifact-publication rollback, concurrent memory edits, deletion/disable behavior, persisted reload and migration downgrade/upgrade preserving existing conversations and Memory.

The expanded `scripts/chat_smoke.py` passed browser → API → worker → fake local provider summary generation, an inspectable Memory link and preserved Chat history, alongside earlier stop/regenerate/restart checks. Desktop/mobile screenshots were inspected and no page errors or horizontal overflow occurred. This tests summary orchestration, not real-model summary quality. Normal tests did not launch real inference.


## Run history filters — 2026-09-26

254 Python tests and 19 frontend tests passed, with lint, TypeScript and production build. API tests verify combined filters before pagination, allocated-versus-requested GPU matching, inclusive dates and invalid UUID/timezone/range rejection. Chromium verified applying combined filters, URL/reload persistence, empty results and mobile layout against a temporary deployment. Initial frontend validation found an obsolete ambiguous test selector and two lint issues; these were fixed before the passing checks. An early browser attempt used the previous build and was rerun after rebuilding.


## Local agent and preview acceptance — 2026-09-26

A disposable Docker worker → private Runner bridge → existing Ollama `qwen3:8b` agent Run retrieved an agent-scoped fixture memory naming Cobalt and produced a Markdown report naming Cobalt. It was a manual local Run; no scheduled or cloud operation was tested. The temporary deployment was removed.

The user-approved preview upgrade to develop `b06edac` completed at http://127.0.0.1:8765. SQLite backup integrity checked successfully before migration; API, worker and scheduler are healthy and local provider discovery returns `qwen3:8b`. Existing data and the prior checkout were retained. The user authorized subsequent development updates/restarts.


## Sandboxed project validation — 2026-09-26

263 Python tests and 20 frontend tests passed, with Python lint/format and frontend format/lint/TypeScript/production build. Five opt-in tests passed through the installed Cursor native sandbox: successful and failed commands, cancellation, timeout termination and sanitized command environment. The standalone probe confirmed workspace writes while outside/Git metadata/global temporary writes and loopback network access were denied. Chromium passed project → saved validation Run → visible command results/JSON artifact, mobile layout, original checkout/index preservation and runner outage behavior. An initial browser attempt used an exact implicit-label selector that included the saved textarea content after remount; correcting that test selector produced the passing run. No coding model or cloud tokens were used.


## Bounded Cursor coding — 2026-09-26

283 Python tests and 21 frontend tests passed, with Python lint/format and frontend format/lint/TypeScript/production build. The opt-in real Cursor browser test passed fresh worktree preparation, two selected source edits, Git-compatible diff/JSON artifacts, the review UI and automatic saved validation through the installed native sandbox. The original dirty checkout and index were unchanged. Mobile review output was inspected; provider cloud inference was explicitly enabled only for this test.

An initial end-to-end attempt found a background Cursor helper keeping its owned process group alive after the main CLI exited. Identity-checked pidfd cleanup fixed this; regressions cover success, nonzero exit, invalid output, inherited pipes and an unrelated process remaining untouched. The complete real test then passed. Existing bundle-size and TestClient deprecation advisories remain. No Codex execution is claimed.


## Multiple native validation commands — 2026-09-27

The first AI Station self-development attempt applied its documentation proposal in an owned worktree but failed validation: the provider omitted a final newline, and the native helper consumed the shared policy before command two. This attempt is not a passed acceptance test. The prompt now encodes exact content as JSON; each validation command receives a fresh exclusive policy. Two opt-in real native-sandbox regression cases passed, including a second command after a failing first command. The fake CI helper now models policy consumption. The complete self-development repeat remains pending deployment of this correction.


## Local Chat text attachments — 2026-09-27

293 Python tests and 23 frontend tests passed, with lint/format, TypeScript and production build. A Chromium fake-provider smoke confirmed selected file contents in the actual provider request, a persisted download link after API restart, regeneration, summaries, silent-provider cancellation and mobile layout. The attachment was a synthetic Python snippet; no real model inference or external transmission was used. Backend regressions verify bounded input, rejection before persistence, safe text downloads, hashes/provenance, immutable regeneration context, conversation separation and summary coverage of attached text.


## Final local deployment and self-development — 2026-09-27

Reviewed implementation `3926405` was deployed with a verified SQLite backup and retained release checkouts. The final Docker image and fresh isolated fake-executor/browser/restart/shutdown smoke passed. API, native Runner, worker/scheduler and local provider discovery are healthy. Real model/runtime scans observed 18 files and three runtime instances without modifying external resources.

The user-approved real Cursor self-development repeat passed: preparation `c2e12ab4-aef7-44b4-9350-e0463dafb65d`, coding `a5ed6ac9-956c-41c5-9630-9a69d91e9210`, validation `f550e8b0-b41e-4142-bee7-ae04dc5a032d`. The documentation proposal's hash matched exactly, both Python syntax commands passed, and active HEAD/status/index were unchanged. The preserved worktree still awaits human review; no proposal commit/merge/deployment occurred. See [scope and limitations](mvp-acceptance.md).


## Sandboxed project dependency installation — 2026-10-09

`./scripts/check.sh`: 538 Python tests passed (5 skipped), including vendor-wheel install through the fake sandbox helper, manifest URL/VCS rejection, stale/unowned API guards, runner replay/permissions/cancellation, and time-limit failure without a success report. Frontend lint, TypeScript, 59 component tests and production build passed. Existing bundle-size and TestClient deprecation advisories remain.

Normal tests never contacted PyPI. Vendor mode installed a disposable local wheel into a worktree `.venv` and imported it. PyPI mode is covered by parser/plan/policy unit tests and public-DNS fail-closed checks, not a live download. Claude Code remains untested and unavailable.


## Unique snippet replacements in coding proposals — 2026-10-09

`./scripts/check.sh`: 547 Python tests passed (5 skipped), including unique exact substring application, sequential replacements, rejection of missing/ambiguous/mixed/oversized/delete-shaped payloads, prompt contract text, and a fake local-inference integration that applied a README snippet plus a new file while the original checkout stayed unchanged. Frontend lint, TypeScript, 60 component tests and production build passed. Complete file rewrites remain accepted. File deletion stays unsupported. Claude Code remains untested and unavailable.

## Automatic unused worktree expiry — 2026-10-09

`./scripts/check.sh`: 539 Python tests passed (5 skipped), including scheduled expiry through the existing removal Run, skip of pinned/future/busy cases, and keep pinning. Frontend lint, TypeScript, 60 component tests and production build passed. Existing bundle-size and TestClient deprecation advisories remain. Existing worktrees stay unscheduled. Claude Code remains untested and unavailable.

## Chat provider registry and secret references — 2026-10-09

`./scripts/check.sh`: 593 Python tests passed (5 skipped), including builtin local seeding, explicit provider selection, rejection of credentials in URLs and plaintext secret refs, fail-closed missing secrets, write-only stored secrets omitted from API responses, `external_ai` on external Runs, and queued-run failure when the secret reference changes. HTTP is mocked; no cloud API was called. Frontend lint, TypeScript, 68 component tests and production build passed. Pixel vision remains unavailable. Real OpenAI/Anthropic completions are not claimed. Claude Code remains untested and unavailable.

## Oversized conversation-summary message chunking — 2026-10-09

`./scripts/check.sh`: 632 Python tests passed (5 skipped), including labeled character-range chunks, persisted coverage offsets, remainder inclusion in Chat context, automatic summary of an oversized uncovered message, and migration defaulting existing summaries to offset 0. Frontend lint, TypeScript, 78 component tests and production build passed. Embeddings remain unconfigured. Workflow memory production is not in this increment. Claude Code remains untested and unavailable.

## Opt-in workflow observation memory — 2026-10-09

`./scripts/check.sh`: 637 Python tests passed (5 skipped), including successful telemetry observations with source Run provenance, skip of memory_search and reports, fail-closed missing permission and write errors, and 12,000-character excerpts with the full JSON artifact retained. Frontend lint, TypeScript, 79 component tests and production build passed. Embeddings remain unconfigured. Existing agents keep workflow memory off. Claude Code remains untested and unavailable.

## Optional memory embeddings with explicit local setup — 2026-10-09

`./scripts/check.sh`: 641 Python tests passed (5 skipped), including fail-closed missing setup, rejection of public endpoints and `/embeddings` paths, health/index/search Runs, refusal of all-zero vectors, and migration that preserves existing memories. Frontend lint, TypeScript, 80 component tests and production build passed. No embedding weights were downloaded. Cloud embedding providers remain unavailable. Claude Code remains untested and unavailable.

## Data-preserving upgrade backups — 2026-10-09

`./scripts/check.sh`: 669 Python tests passed (5 skipped), including `VACUUM INTO` SQLite backup artifacts with integrity_check, cancel deleting a partial copy, unpublished restore/rollout, interrupted-run acknowledgement without replay, and launcher/compose bind-mount invariants. Frontend lint, TypeScript, 88 component tests and production build passed. Restore, image rollout and LAN publish remain unpublished. Claude Code remains untested and unavailable.

## Unified Home activity — 2026-10-09

Frontend lint, TypeScript, 90 component tests and production build passed. Home attention Stop/Mark inspected use the existing cancel and interrupted-acknowledgement APIs without restore, replay or granting approvals. Command palette Actions include backup readiness (`?focus=maintenance`). Skip link and list semantics are present. Broader workspace keyboard/accessibility coverage remains open. Claude Code remains untested and unavailable.

## Loopback operator session — 2026-10-09

`./scripts/check.sh`: 670 Python tests passed (5 skipped), including session issue on password store, 401 without the `ais_operator` cookie, public health/login, login/logout, and unpublished LAN bind. Frontend lint, TypeScript, 91 component tests and production build passed. Node registration still requires the loopback session and does not open a LAN listener. Remote nodes still do not execute work. Claude Code remains untested and unavailable.

## Workspace keyboard routing — 2026-10-09

Frontend lint, TypeScript, 93 component tests and production build passed. Skip link focuses `#main`. Control K opens the command palette; choosing Home activity moves focus into the workspace. No Python changes in this slice. Broader workspace accessibility remains open. LAN publish and remote execution stay unpublished. Claude Code remains untested and unavailable.

## Coding review keyboard, cumulative totals and artifacts — 2026-10-09

Frontend lint, TypeScript, 96 component tests and production build passed. Review lists files for arrow-key selection, shows one selected patch, labels cumulative totals against the task base, and links the stored `changes.diff` / review JSON artifacts. Commit, repair and publication still use the existing endpoints. No Python or Host Runner changes. Pre-existing Prettier drift in unrelated files was left untouched. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Route announcements after navigation — 2026-10-09

Frontend lint, TypeScript, 96 component tests and production build passed. In-app navigation updates `document.title` to `{workspace} · AI Station` and a polite live region announces `{workspace} workspace` after the first load. Skip-link focus is unchanged. Overlay focus traps were already Radix Dialogs and were not reimplemented. Remaining keyboard, label and contrast work stays open. No Python changes. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Inspect-only held and stale leases — 2026-10-09

`./scripts/check.sh`: 671 Python tests passed (5 skipped), including GET `/api/system/status` listing held leases, marking expired ones stale, `replay: false`, refusing POST, and leaving the expired Run in `preparing`. Frontend lint, TypeScript, 97 component tests and production build passed. System shows expired leases and paused recovery when no worker is available, without restore/replay/requeue controls. Recovery still happens only on the next worker tick. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Workspace labels, dialog titles and contrast — 2026-10-09

Frontend lint, TypeScript, 97 component tests and production build passed. Command palette, Library, model picker and media search fields expose accessible names. Overlay dialogs keep Radix titles (command palette, model picker, Library picker, edit/trash). Sidebar muted text, navigation labels, placeholders and link chrome use AA contrast tokens; 6px/7px decorative type was raised. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Inspect-only SQLite backup re-check — 2026-10-09

`./scripts/check.sh`: 672 Python tests passed (5 skipped), including GET `/api/maintenance/backups/{run_id}` repeating integrity_check and hashing the stored copy, reporting a damaged file without writing the live database, 409 on missing/canceled copies, and unpublished restore/rollout. Frontend lint, TypeScript, 98 component tests and production build passed. System **Inspect copy** re-checks a successful backup in place and does not offer Restore. Image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Loopback session Sign out in workspace chrome — 2026-10-09

Frontend lint, TypeScript, 99 component tests and production build passed. After an operator password is stored, the top bar shows **Sign out** for the loopback session and posts the existing logout endpoint. No LAN bind control is offered. Settings still has the same Sign out. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.
