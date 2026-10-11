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

## Loopback session idle timeout — 2026-10-09

`./scripts/check.sh`: 675 Python tests passed (5 skipped), including cookie flags (httpOnly, SameSite=strict, not Secure, Path=/, idle Max-Age), activity refreshing `last_seen_at`, idle expiry deleting the HMAC, absolute 12-hour expiry winning over recent activity, and legacy sessions starting an idle clock on first use. Frontend lint, TypeScript, 100 component tests and production build passed. Settings and the login screen state the 30-minute idle / 12-hour absolute policy. LAN publish remains unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Inspect-only compose image comparison — 2026-10-09

`./scripts/check.sh`: 683 Python tests passed (5 skipped), including Host Runner refusal of build/tag/stop argv, missing Docker, missing tag, stale running image ID vs rebuilt `ai-station:local`, ignoring unrelated compose projects, GET `/v1/station-image` without POST rollout, GET `/api/maintenance/image` comparing tag vs running API/worker/scheduler, and unpublished rollout when the runner is down. Frontend lint, TypeScript, 101 component tests and production build passed. System **Inspect running image** does not offer Restore or Rollout. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Download stored SQLite backup copies — 2026-10-09

`./scripts/check.sh`: 683 Python tests passed (5 skipped), including listing the SQLite artifact on GET `/api/maintenance/backups` and downloading it as `SQLite format 3` without restore. Frontend lint, TypeScript, 101 component tests and production build passed. System **Download copy** uses the existing artifact file endpoint and does not offer Restore. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home attention keyboard and labelled landmarks — 2026-10-09

`./scripts/check.sh`: 683 Python tests passed (5 skipped). Frontend lint, TypeScript, 102 component tests and production build passed. Home attention rows form one keyboard sequence (arrows, Home, End, Enter inspects). Stop and Mark inspected name the selected work and stay on that row. Activity sections, compute telemetry meters and the resource chart expose accessible names. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home notice Mark read — 2026-10-09

Frontend lint, TypeScript, 102 component tests and production build passed. Home **Mark read** posts the existing `/api/notices/{id}/read` body `{ "read": true }` and does not retry, restore or replay the related Run. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home parked-run Approve and Deny — 2026-10-09

Frontend lint, TypeScript, 104 component tests and production build passed. Home **Approve and queue** / **Deny** post the existing `/api/runs/{id}/approval` resolutions `granted` and `denied`. Granting queues the parked Run; it does not start tools or inference from Home. Deny cancels it. Stop is not offered for `waiting_for_approval`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Runs table keyboard selection — 2026-10-09

Frontend lint, TypeScript, 105 component tests and production build passed. The Runs table is one keyboard sequence (arrows, Home, End, Enter inspects). Duplicate inspect icons stay out of the tab order. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Library grid keyboard selection — 2026-10-09

Frontend lint, TypeScript, 106 component tests and production build passed. The Library collection is one keyboard sequence (arrows, Home, End, Enter inspects). Inspect names include the artifact title and short id. Decorative type icons stay out of the tab order. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat transcript keyboard and landmarks — 2026-10-09

Frontend lint, TypeScript, 107 component tests and production build passed. Conversation messages form one keyboard sequence (arrows, Home, End, Enter inspects a Run when present). Inspect run and Copy name the speaker and short message id and stay on the selected message. The transcript is a labelled Messages landmark. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agents list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 108 component tests and production build passed. The Agents list is one keyboard sequence (arrows, Home, End, Enter inspects). Inspect names include the agent name and short id. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Memory list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 109 component tests and production build passed. The Memory list is one keyboard sequence (arrows, Home, End, Enter inspects). Inspect names include the memory type and short id. Decorative pin icons stay out of the tab order. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat conversation history keyboard — 2026-10-09

Frontend lint, TypeScript, 110 component tests and production build passed. Chat history is one keyboard sequence (arrows, Home, End, Enter opens). Inspect names include the conversation title and short id. Decorative message icons stay out of the tab order. The list is a labelled Conversations landmark. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Projects list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 111 component tests and production build passed. The Projects list is one keyboard sequence (arrows, Home, End, Enter inspects). Inspect names include the project name and short id. Decorative repository icons stay out of the tab order. Shared `useListKeyboard` covers this list without changing already-shipped Home/Runs/Library/Chat/Agents/Memory sequences. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Models list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 112 component tests and production build passed. Observed model files and curated definitions are each one keyboard sequence (arrows, Home, End, Enter inspects). Inspect names include the filename or definition name and short id. Decorative type icons stay out of the tab order. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding conversations keyboard selection — 2026-10-09

Frontend lint, TypeScript, 113 component tests and production build passed. Coding conversation cards form one keyboard sequence (arrows, Home, End, Enter opens). Inspect names include the session title and short id. Decorative open icons stay out of the tab order. The list is a labelled Coding conversations landmark. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Connectors list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 114 component tests and production build passed. Named HTTP GET connectors form one keyboard sequence (arrows, Home, End, Enter inspects the last check when one exists). Inspect, Check GET and Remove names include the connector name and short id. Browser/GitHub/email adapters stay listed as unavailable and are not in that inspect sequence. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Runtime observations keyboard selection — 2026-10-09

Frontend lint, TypeScript, 115 component tests and production build passed. Runtime observation rows form one keyboard sequence (arrows, Home, End, Enter inspects the source Run when one exists). Inspect names include the runtime name and short id. Observation still does not control external processes. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat providers keyboard selection — 2026-10-09

Frontend lint, TypeScript, 116 component tests and production build passed. Registered chat providers form one keyboard sequence (arrows, Home, End). Remove names include the provider name and short id and stay on the selected row. There is no inspectable provider Run. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Project worktrees keyboard selection — 2026-10-09

Frontend lint, TypeScript, 117 component tests and production build passed. Prepared worktrees form one keyboard sequence (arrows, Home, End, Enter inspects the preparation Run). Inspect, install, validate, keep and remove names include the branch and short id. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Backup copies keyboard selection — 2026-10-09

Frontend lint, TypeScript, 118 component tests and production build passed. Recent SQLite backup copies form one keyboard sequence (arrows, Home, End, Enter inspects the backup Run). Inspect copy and Download copy names include the short Run id and stay on the selected row. Restore and image rollout stay unpublished. Reuses `useListKeyboard`. No Python or Host Runner changes. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Worker leases keyboard selection — 2026-10-09

Frontend lint, TypeScript, 119 component tests and production build passed. Held worker leases form one keyboard sequence (arrows, Home, End, Enter inspects the Run). Inspect names include the short Run id. The list still does not recover, requeue or restore. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Library picker keyboard selection — 2026-10-09

Frontend lint, TypeScript, 120 component tests and production build passed. The Library input picker is one keyboard sequence (arrows, Home, End, Enter selects or deselects). Choose names include the filename and short id. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Interrupted Runs keyboard selection — 2026-10-09

Frontend lint, TypeScript, 121 component tests and production build passed. Interrupted Runs form one keyboard sequence (arrows, Home, End, Enter inspects). Inspect and Mark inspected names include the title and short id. Mark inspected still does not retry, restore or replay. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images Library attach and inline MediaInput keyboard — 2026-10-09

Frontend lint, TypeScript, 123 component tests and production build passed. Images Edit/Recompose/Upscale attach existing Library files through the shared picker without another upload. The inline Audio/Avatars MediaInput list is one keyboard sequence (arrows, Home, End, Enter attaches) with unique Choose names. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Integration checks keyboard selection — 2026-10-09

Frontend lint, TypeScript, 124 component tests and production build passed. Integration checks form one keyboard sequence (arrows, Home, End). Check names are unique. There is no inspectable diagnostic Run. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Worker heartbeats keyboard selection — 2026-10-09

Frontend lint, TypeScript, 125 component tests and production build passed. Registered workers form one keyboard sequence (arrows, Home, End). Worker names include the worker id. There is no inspectable heartbeat Run. Held leases stay a separate inspect-only list. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Compose containers keyboard selection — 2026-10-09

Frontend lint, TypeScript, 126 component tests and production build passed. Running compose containers form one keyboard sequence (arrows, Home, End) after Inspect running image. Container names include the service and short id. Rollout remains unpublished. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Model picker keyboard selection — 2026-10-09

Frontend lint, TypeScript, 127 component tests and production build passed. The Chat/Coding model picker is one keyboard sequence (arrows, Home, End, Enter marks). llama.cpp and local-server models share that list. Use model still applies the choice. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Nodes list keyboard selection — 2026-10-09

Frontend lint, TypeScript, 128 component tests and production build passed. The node inventory is one keyboard sequence (arrows, Home, End). Revoke names include the node name and short id and stay on the selected row. There is no inspectable node Run. LAN transport stays unpublished. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Unpublished connector adapters keyboard — 2026-10-09

Frontend lint, TypeScript, 129 component tests and production build passed. Unpublished connector kinds form one keyboard sequence (arrows, Home, End) with unique Adapter names. They stay unavailable; there is no inspectable adapter Run. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Run event timeline keyboard selection — 2026-10-09

Frontend lint, TypeScript, 130 component tests and production build passed. The Run inspector Activity/All-events page is one keyboard sequence (arrows, Home, End) with unique Event names including type and sequence. Older and newer paging stays outside the list. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Workflow steps keyboard selection — 2026-10-09

Frontend lint, TypeScript, 131 component tests and production build passed. Workflow child steps on a parent Run are one keyboard sequence (arrows, Home, End, Enter inspects) with unique Inspect names including the step key and short Run id. Cancel stays outside the list. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agent execution history keyboard selection — 2026-10-09

Frontend lint, TypeScript, 132 component tests and production build passed. Agent execution history is one keyboard sequence (arrows, Home, End, Enter inspects) with unique Inspect names including capability or step tool and short Run id. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Search sources keyboard selection — 2026-10-09

Frontend lint, TypeScript, 133 component tests and production build passed. Retrieved search source cards are one keyboard sequence (arrows, Home, End, Enter opens the public URL) with unique Source names including title and id. Rel stays `noopener noreferrer`. This is search, not browser automation. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Fetched pages keyboard selection — 2026-10-09

Frontend lint, TypeScript, 134 component tests and production build passed. Reviewed HTTP GET page cards are one keyboard sequence (arrows, Home, End, Enter opens the public URL) with unique Page names. Rel stays `noopener noreferrer`. JavaScript is not executed and page HTML is not rendered. Reuses `useListKeyboard`. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home attention shared list keyboard — 2026-10-09

Frontend lint, TypeScript, 139 component tests and production build passed. Home attention reuses `useListKeyboard`. Inspect, Stop, Mark inspected, Mark read, Approve and Deny names include a short Run or notice id. Enter still inspects; those actions stay on the selected row and still use the existing cancel, interrupted-acknowledgement, notice-read and approval endpoints. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding review file listbox shared keyboard — 2026-10-09

Frontend lint, TypeScript, 139 component tests and production build passed. Coding review changed files reuse `useListKeyboard` as a listbox: arrows/Home/End choose a file, unique File names, and only the selected patch is shown. Enter does not open a Run. Commit, repair and publication still use the existing endpoints. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home activity list keyboard — 2026-10-09

Frontend lint, TypeScript, 140 component tests and production build passed. Upcoming schedules, enabled agents, recent conversations, recent artifacts and runtime observations each reuse `useListKeyboard` with unique Inspect names. Scheduled vs enabled agents stay distinct. Enter inspects the agent, conversation or artifact; runtime rows open System and do not invent an observation Run. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding exploration step keyboard — 2026-10-09

Frontend lint, TypeScript, 141 component tests and production build passed. Repository exploration steps reuse `useListKeyboard` with unique Step names. Enter does not invent an exploration Run; observations stay on the coding review. File listbox, commit, repair and publication are unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding file checkboxes keyboard — 2026-10-09

Frontend lint, TypeScript, 148 component tests and production build passed. Explicit Coding and assistant file paths reuse `useListKeyboard` as checkboxes with unique Edit file names. Space or Enter removes the focused path and does not start a coding Run. Automatic discovery, consent, commit, repair and publication are unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agent policy checkboxes keyboard — 2026-10-09

Frontend lint, TypeScript, 149 component tests and production build passed. Agent approval, retry and notice policies reuse `useListKeyboard` with unique Approval, Retry and Notice names. Space or Enter selects the focused row and does not invent a Run. Saved policies still park, retry from a snapshot or write in-app notices through the existing endpoints. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Saved Chat transcript attachments keyboard — 2026-10-09

Frontend lint, TypeScript, 150 component tests and production build passed. Attachments already saved on a Chat message reuse `useListKeyboard` as a nested sequence with unique Saved attachment names. Enter opens the selected file and does not inspect a Run. Composer staging, pixel vision and download boundaries are unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home CPU/RAM metric cards keyboard — 2026-10-09

Frontend lint, TypeScript, 151 component tests and production build passed. Home CPU, memory, storage and in-progress Run cards reuse `useListKeyboard` with unique Metric names. Enter inspects Runs from that card; CPU/memory/storage stay live telemetry on Home and do not invent a telemetry Run. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agent workflow mode keyboard — 2026-10-09

Frontend lint, TypeScript, 152 component tests and production build passed. Bounded tool calling and sequential or gated workflow mode reuse `useListKeyboard` with unique Tool calling and Workflow names. Space or Enter selects the focused row and does not invent a Run. Saved sequential/gated steps and bounded registry calls still use the existing endpoints. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat search toggle keyboard — 2026-10-09

Frontend lint, TypeScript, 153 component tests and production build passed. The Chat Search the web toggle reuses `useListKeyboard` with a unique Search name. Space or Enter selects it and does not send. Query, sources, opt-in search and browser automation remain unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Memory pin/disable keyboard — 2026-10-09

Frontend lint, TypeScript, 154 component tests and production build passed. Memory pin and enabled flags reuse `useListKeyboard` with unique Memory names. Space or Enter selects the focused row and does not invent a Run. Disabled or unpinned entries still leave historical Chat snapshots unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation auto-summary keyboard — 2026-10-09

Frontend lint, TypeScript, 155 component tests and production build passed. Automatic conversation-memory maintenance reuses `useListKeyboard` with a unique Summary name. Space or Enter selects it, PATCHes the existing opt-in, and does not POST a summary Run. Manual Update summary and disabled-memory suppression are unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Project Git policy keyboard — 2026-10-09

Frontend lint, TypeScript, 156 component tests and production build passed. Project Git workflow policy checkboxes reuse `useListKeyboard` with unique Policy names. Space or Enter selects commit, push or integration-PR intent and does not invent a Git Run. Force push, production PRs and automatic merge stay disabled. Saving still does not commit, push or open a PR. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding consent keyboard — 2026-10-09

Frontend lint, TypeScript, 159 component tests and production build passed. Coding start, follow-up and assistant external-AI consent reuse `useListKeyboard` with a unique Consent name. Space or Enter selects it and does not start a coding Run or send a follow-up. Local AI still needs no consent. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## GitHub publication approval keyboard — 2026-10-09

Frontend lint, TypeScript, 162 component tests and production build passed. GitHub publication approval on the commit Run and in the assistant reuses `useListKeyboard` with a unique Publication name. Space or Enter selects it and does not POST a publication Run. Exact-scope approval, reconcile and draft-PR publication remain the existing endpoints. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Commit review acknowledgement keyboard — 2026-10-09

Frontend lint, TypeScript, 165 component tests and production build passed. Coding and assistant review acknowledgement reuses `useListKeyboard` with a unique Review name. Space or Enter selects it and does not queue a `coding.commit` Run. File listbox, repair and publication remain unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding file-discovery keyboard — 2026-10-09

Frontend lint, TypeScript, 167 component tests and production build passed. Automatic Coding and assistant file discovery reuses `useListKeyboard` with a unique Explore name. Space or Enter selects it and does not start a coding Run. Explicit Edit file checkboxes remain the existing sequence. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Local AI repair budget keyboard — 2026-10-09

Frontend lint, TypeScript, 171 component tests and production build passed. Coding and assistant Local AI repair budgets reuse `useListKeyboard` with unique Repair names. Space or Enter selects the focused budget and does not start a coding Run. Automatic repair still uses the existing `max_repair_attempts` field; Cursor and Codex still have no repair budget. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat this-turn execution mode keyboard — 2026-10-09

Frontend lint, TypeScript, 175 component tests and production build passed. Chat this-turn execution mode reuses `useListKeyboard` with unique Turn names. Space or Enter selects Conversation default, Conversation only or Platform assistant and does not send or PATCH conversation settings. Saved conversation Mode remains the existing settings select. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images/Audio/Avatars GPU target keyboard — 2026-10-09

Frontend lint, TypeScript, 177 component tests and production build passed. Images, Audio and Avatars GPU targets reuse `useListKeyboard` with unique Target GPU names. Space or Enter selects Auto or a discovered GPU and does not queue a photo, speech or avatar Run. llama.cpp allocation checkboxes remain the existing sequence. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images Generate backend keyboard — 2026-10-09

Frontend lint, TypeScript, 180 component tests and production build passed. Images Generate Qwen/Juggernaut backends reuse `useListKeyboard` with unique Backend names. Space or Enter selects the focused backend and does not queue a photo Run. Edit, Recompose and Upscale still force Qwen. Seed and negative prompt still appear only for Juggernaut. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant action keyboard — 2026-10-09

Frontend lint, TypeScript, 183 component tests and production build passed. Assistant Action radios reuse `useListKeyboard` with unique Action names. Space or Enter selects Auto, conversation, image, speech, avatar, agent, coding, commit, publish or owned llama.cpp load/unload and does not send. Unpublished adapters stay absent from that list. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Avatars Quality and Clip length keyboard — 2026-10-09

Frontend lint, TypeScript, 187 component tests and production build passed. Avatars Quality and Clip length radios reuse `useListKeyboard` with unique Quality and Clip names. Space or Enter selects 256/384/512 px or 17–81 frames and does not queue an EchoMimic Run. Advanced steps, seed and GPU stay unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Chat saved Mode and Provider keyboard — 2026-10-09

Frontend lint, TypeScript, 191 component tests and production build passed. Saved conversation Mode and Provider radios reuse `useListKeyboard` with unique Mode and Provider names. Space or Enter selects Platform assistant, Conversation only or a registered provider and does not create, save or send. This-turn Turn radios remain the existing override and still do not rewrite saved Mode. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding executor keyboard — 2026-10-09

Frontend lint, TypeScript, 194 component tests and production build passed. Coding Auto/Local AI/Cursor/Codex radios reuse `useListKeyboard` with unique Executor names. Space or Enter selects the focused executor and does not start a coding Run. Claude Code stays absent. Preferred-executor Auto and consent still use the existing fields. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding project keyboard — 2026-10-09

Frontend lint, TypeScript, 197 component tests and production build passed. Coding project radios reuse `useListKeyboard` with unique Project names. Space or Enter selects the focused registered project and does not start a coding Run. Preferred executor remains a displayed hint; Auto still follows the saved project preference. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images operation keyboard — 2026-10-09

Frontend lint, TypeScript, 200 component tests and production build passed. Images Generate/Edit/Recompose/Upscale tabs reuse `useListKeyboard` with unique Operation names. Space or Enter selects the focused operation and does not queue a photo Run. Edit, Recompose and Upscale still force Qwen. Generate backend radios remain the existing Qwen/Juggernaut sequence. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant coding project keyboard — 2026-10-09

Frontend lint, TypeScript, 200 component tests and production build passed. Assistant coding scope reuses the Coding `ProjectChoiceList` with unique Project names. Space or Enter selects a registered project and does not send. Preferred executor remains a displayed hint. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant GGUF and owned-runtime keyboard — 2026-10-09

Frontend lint, TypeScript, 207 component tests and production build passed. Assistant load/unload radios reuse `useListKeyboard` with unique GGUF and Runtime names. Space or Enter selects a discovered language-model GGUF or an owned llama.cpp instance and does not send. External/Ollama servers and stopped instances stay off the unload list. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant proposal and commit keyboard — 2026-10-09

Frontend lint, TypeScript, 211 component tests and production build passed. Assistant commit/publish radios reuse `useListKeyboard` with unique Proposal and Commit names. Space or Enter selects a reviewed coding proposal or successful reviewed commit from this conversation and does not send, commit or publish. Review acknowledgement and GitHub approval remain the existing sequences. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding Cursor/Codex model keyboard — 2026-10-09

Frontend lint, TypeScript, 215 component tests and production build passed. Coding start Cursor/Codex models reuse `useListKeyboard` with unique Model names. Space or Enter selects Auto or an installed CLI catalog model and does not start a coding Run. Auto remains the selected provider's CLI default and never a silent provider switch. Local AI still uses the existing llama.cpp picker. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant Cursor/Codex model select — 2026-10-09

Frontend lint, TypeScript, 216 component tests, production build and `./scripts/check.sh` (685 passed, 5 skipped) passed. Assistant Cursor/Codex coding reuses the Coding native model radios. Space or Enter selects Auto or an installed CLI catalog model and does not send. Auto remains the selected provider's CLI default. The selected model is stored on `CodingScope` and applied to the existing Cursor/Codex coding Task; local coding still uses the conversation model. No Host Runner or schema migration. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant Cursor/Codex automatic file discovery — 2026-10-09

Frontend lint, TypeScript, 217 component tests, production build and `./scripts/check.sh` (687 passed, 5 skipped) passed. Assistant Cursor and Codex coding reuse the existing Explore checkbox and worktree discovery path. Space or Enter selects it and does not send. Cursor and Codex stay repository-only; public GET remains Local AI only. Explore plus explicit files is still rejected. No Host Runner or schema migration. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images workspace inline results — 2026-10-11

Frontend lint, TypeScript, 224 component tests and production build passed. Images no longer navigates to the Run inspector after queueing. The workspace keeps live GPU wait/progress, Stop, the finished image, shared source/derived lineage and a logs link; the Run ID stays in the URL for refresh. Library `mode`/`input` deep links still remount the composer. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images result reuse — 2026-10-11

Frontend lint, TypeScript, 225 component tests and production build passed. A finished Images result can Edit, Recompose or Upscale that artifact in the same workspace. Those links stage it as the next source, keep the previous Run in the URL for the still-visible output, and do not queue a Run. Library's equivalent actions are unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent enable from conversation — 2026-10-11

Frontend lint, TypeScript, 227 component tests and production build passed. After `agent.create`, the conversation loads the saved definition and can enable or pause it through `POST /api/agents/{id}/enabled` with the expected version. That does not invent a conversation Run and does not call Run now. Open in Agents remains available for tools, schedule and execution. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Audio result voice reuse — 2026-10-11

Frontend lint, TypeScript, 229 component tests and production build passed. A finished Audio result can be used as the next voice reference in the same workspace. That link stages the WAV as the source, keeps the previous Run in the URL for the still-visible output, and does not queue a Run. Library's equivalent action is unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Avatars source staging — 2026-10-11

Frontend lint, TypeScript, 231 component tests and production build passed. Images, Audio and Library can stage a portrait or WAV into Avatars through `?image=` / `?audio=` without queueing a Run. The Avatars composer remounts on those sources and keeps a generation Run in the URL separately. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant media workspace reuse — 2026-10-11

Frontend lint, TypeScript, 232 component tests and production build passed. Inline conversation images can Edit, Recompose, Upscale or become an Avatars portrait without another Run. WAV results can open in Audio or become Avatars speech the same way. Next-message Use as image/voice reference is unchanged. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent definition review — 2026-10-11

Frontend lint, TypeScript, 233 component tests and production build passed. After `agent.create`, the conversation shows the saved schedule, tools, skills and instructions from `GET /api/agents/{id}` before enable or pause. That does not invent a conversation Run and does not call Run now. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent execution history — 2026-10-11

Frontend lint, TypeScript, 235 component tests and production build passed. After `agent.create`, the conversation shows next/last run and ordinary execution history from `GET /api/agents/{id}`. Arrow keys choose a history Run; Enter inspects it with unique Inspect names. A waiting approval links to that Run. Enable/pause still uses the existing endpoint and does not call Run now. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent duplicate — 2026-10-11

Frontend lint, TypeScript, 236 component tests and production build passed. After `agent.create`, Duplicate as draft posts `POST /api/agents/{id}/duplicate` with the expected version. The copy stays disabled and links into Agents. That does not invent a conversation Run and does not call Run now. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Media result Library details — 2026-10-11

Frontend lint, TypeScript, 238 component tests and production build passed. Images, Audio, Avatars and assistant inline results reuse Library Edit details and Trash with unique names. Saving PATCHes the existing artifact endpoint and does not queue a Run. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Images workspace retry — 2026-10-11

Frontend lint, TypeScript, 241 component tests and production build passed. A failed, canceled or interrupted Images generation can Retry as a new run in the workspace through the existing `POST /api/images/runs/{id}/retry` endpoint. The new Run ID replaces the previous one in the URL; the inspector is not opened. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent workflow retry — 2026-10-11

Frontend lint, TypeScript, 243 component tests and production build passed. Execution history in the conversation and Agents can Retry as a new workflow through `POST /api/runs/{id}/retry-workflow` when `retry.allowed` is set. That does not call Run now. The conversation also shows a saved manual retry policy. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Library collection actions — 2026-10-11

Frontend lint, TypeScript, 244 component tests and production build passed. Library collection cards and Run inspector artifact cards reuse Edit details, Trash and Restore with unique names. Saving still PATCHes or DELETEs the existing artifact endpoint and does not invent a Run. Enter inspects. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant image retry — 2026-10-11

Frontend lint, TypeScript, 246 component tests and production build passed. A failed, canceled or interrupted Images child in the conversation can Retry as a new run through the existing `POST /api/images/runs/{id}/retry` endpoint. The conversation stays on that transcript; the inspector is not opened. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home interrupted image retry — 2026-10-11

Frontend lint, TypeScript, 248 component tests and production build passed. An interrupted `photo_pipe` Run on the Home attention list can Retry as a new run through the existing `POST /api/images/runs/{id}/retry` endpoint. Home stays in place; the inspector is not opened. Mark inspected still does not replay. Interrupted non-image Runs and Audio/avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Home agent workflow retry — 2026-10-11

`./scripts/check.sh`: 689 Python tests passed (5 skipped). Frontend lint, TypeScript, 249 component tests and production build passed. A failed agent notice on Home whose saved policy allows manual retry can Retry as a new workflow through `POST /api/runs/{id}/retry-workflow` using the parent workflow id. That does not call Run now or Mark read. Audio and avatar retries stay unpublished. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent approval — 2026-10-11

Frontend lint, TypeScript, 251 component tests and production build passed. A parked agent Run in the conversation or Agents can Approve and queue or Deny through the existing `POST /api/runs/{id}/approval` endpoint. Granting queues that Run and does not start tools, call Run now, or open the inspector. Deny cancels it. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent Stop — 2026-10-11

Frontend lint, TypeScript, 253 component tests and production build passed. An in-progress agent Run in conversation or Agents history can Stop through the existing `POST /api/runs/{id}/cancel` endpoint. That does not call Run now or open the inspector. Waiting Runs keep Approve and Deny instead of Stop. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent report — 2026-10-11

Frontend lint, TypeScript, 255 component tests and production build passed. After `agent.create`, the conversation and Agents show the latest ordinary agent report inline from `GET /api/artifacts?run_id=` and the stored markdown file. Remote Markdown images are omitted. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent search sources — 2026-10-11

Frontend lint, TypeScript, 258 component tests and production build passed. After `agent.create`, the conversation and Agents show independently recorded search sources next to the latest ordinary agent report from that report Run's `metadata.web_search`, or from the matching `web_search` sibling before that copy exists. Enter opens the selected public URL. That is search, not browser automation, and does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent fetched pages — 2026-10-11

Frontend lint, TypeScript, 261 component tests and production build passed. After `agent.create`, the conversation and Agents show independently recorded fetched-page cards next to the latest ordinary agent report from that report Run's `metadata.http_fetch`, or from the matching `http_fetch` sibling before that copy exists. Enter opens the selected public URL. Page HTML is not rendered. JavaScript is not executed. That is reviewed GET, not browser automation, and does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent registry tool calls — 2026-10-11

Frontend lint, TypeScript, 263 component tests and production build passed. After `agent.create`, the conversation and Agents show independently recorded registry tool calls next to the latest ordinary agent report from that report Run's `metadata.tool_calls`. There is no inspectable tool-call Run. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent last-parent workflow steps — 2026-10-11

Frontend lint, TypeScript, 267 component tests and production build passed. After `agent.create`, the conversation and Agents show `workflow.steps` of the last parent next to execution history from `GET /api/agents/{id}`. Enter inspects the child Run. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent saved workflow observations — 2026-10-11

Frontend lint, TypeScript, 267 component tests and production build passed. After `agent.create`, a last-parent workflow step with `memory_id` opens that Memory entry. The conversation can Inspect this agent's memory. Enter still inspects the child Run. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent Run now — 2026-10-11

Frontend lint, TypeScript, 268 component tests and production build passed. After `agent.create`, an enabled idle definition can Run now from the conversation through `POST /api/agents/{id}/run`. The new workflow stays on the transcript; the inspector is not opened. A disabled draft or an already-active Run keeps that control disabled. Tools and schedule stay in Agents. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent skill review — 2026-10-11

Frontend lint, TypeScript, 271 component tests and production build passed. After `agent.create`, attached skills are listed from `GET /api/skills`. Review instructions stays on the selected row. A stored id missing from the catalog stays visible. That does not invent a Skill Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent notice policy — 2026-10-11

Frontend lint, TypeScript, 272 component tests and production build passed. After `agent.create`, a saved in-app notice policy is shown on the definition. Unselected notice kinds stay omitted. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Assistant agent tool review — 2026-10-11

Frontend lint, TypeScript, 275 component tests and production build passed. After `agent.create`, attached tools are listed from `GET /api/agents/tools`. Unavailable tools stay visible and still block activation. A stored name missing from that registry stays visible. That does not invent a tool-selection Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Coding review validation commands — 2026-10-11

Frontend lint, TypeScript, 276 component tests and production build passed. Coding review in the conversation, Coding workspace and proposal inspector lists saved validation commands from `GET /api/runs/{id}/events` on the existing validation Run. There is no inspectable child Run. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agent Enable stays off until activation is possible — 2026-10-11

Frontend lint, TypeScript, 282 component tests and production build passed. Enable in the conversation and Agents stays disabled when saved tools are unavailable or unknown, the model is missing, or web_search/http_fetch lack their saved query or URLs. Pause, Duplicate and Open in Agents stay available. That does not invent a conversation Run or call Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves a local agent model — 2026-10-11

Frontend lint, TypeScript, 283 component tests and production build passed. After `agent.create`, the conversation can save a local model on that definition through `PUT /api/agents/{id}` and the existing model picker. Use model does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves an agent public search query — 2026-10-11

Frontend lint, TypeScript, 284 component tests and production build passed. After `agent.create`, when `web_search` is attached, the conversation can save the public search query through `PUT /api/agents/{id}`. Saving it does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves agent reviewed fetch URLs — 2026-10-11

Frontend lint, TypeScript, 285 component tests and production build passed. After `agent.create`, when `http_fetch` is attached, the conversation can save reviewed public URLs through `PUT /api/agents/{id}`. Saving them does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation removes an unavailable agent tool — 2026-10-11

Frontend lint, TypeScript, 288 component tests and production build passed. After `agent.create`, the conversation can remove an unavailable or unknown attached tool through `PUT /api/agents/{id}`. Removing it does not invent a conversation Run or call Enable. Adding tools stays in Agents. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation removes a missing agent skill — 2026-10-11

Frontend lint, TypeScript, 292 component tests and production build passed. After `agent.create`, the conversation can remove a stored skill missing from `GET /api/skills` through `PUT /api/agents/{id}`. Removing it does not invent a conversation Run or call Enable. Adding skills stays in Agents. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation attaches an operational agent tool — 2026-10-11

Frontend lint, TypeScript, 295 component tests and production build passed. After `agent.create`, the conversation can attach an operational tool from `GET /api/agents/tools` through `PUT /api/agents/{id}`. Adding it does not invent a conversation Run or call Enable. Unpublished adapters cannot be added. Enable stays off until the saved definition can activate. Adding skills and schedule stay in Agents. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation attaches an installed agent skill — 2026-10-11

Frontend lint, TypeScript, 299 component tests and production build passed. After `agent.create`, the conversation can attach an installed skill from `GET /api/skills` through `PUT /api/agents/{id}`. Adding it does not invent a conversation Run or call Enable. At most four skills. Enable stays off until the saved definition can activate. Adding schedule stays in Agents. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves an agent UTC schedule — 2026-10-11

Frontend lint, TypeScript, 300 component tests and production build passed. After `agent.create`, the conversation can save the UTC schedule through `PUT /api/agents/{id}`. Saving it does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves agent approval, retry, notice and workflow policies — 2026-10-11

Frontend lint, TypeScript, 301 component tests and production build passed. After `agent.create`, the conversation can save approval, retry, notice and sequential or gated workflow policies through `PUT /api/agents/{id}`. Saving them does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Bounded tool calling still stays in Agents. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves bounded agent tool calling — 2026-10-11

Frontend lint, TypeScript, 302 component tests and production build passed. After `agent.create`, the conversation can save bounded registry tool calling through `PUT /api/agents/{id}`. Saving it does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves agent instructions — 2026-10-11

Frontend lint, TypeScript, 303 component tests and production build passed. After `agent.create`, the conversation can save the goal and system prompt through `PUT /api/agents/{id}`. Saving them does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves agent identity — 2026-10-11

Frontend lint, TypeScript, 304 component tests and production build passed. After `agent.create`, the conversation can save the name, time limit and expected outcome through `PUT /api/agents/{id}`. Saving them does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves agent description — 2026-10-11

Frontend lint, TypeScript, 305 component tests and production build passed. After `agent.create`, the conversation can save the description through `PUT /api/agents/{id}`. Saving it does not invent a conversation Run or call Enable. Enable stays off until the saved definition can activate. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation inspects agent memory notices — 2026-10-11

Frontend lint, TypeScript, 306 component tests and production build passed. After `agent.create`, attached remember-reports or remember-workflow tools show how observations are stored. That does not invent a conversation Run or call Enable. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Conversation saves a linked agent project — 2026-10-11

Frontend lint, TypeScript, 307 component tests and production build passed. After `agent.create`, the conversation can save a linked project through `PUT /api/agents/{id}`. Saving it tags this agent's Runs for filtering and does not grant coding, Git or repository access. It does not invent a conversation Run or call Enable. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.

## Agents definition editor saves a linked project — 2026-10-11

Frontend lint, TypeScript, 309 component tests and production build passed. The Agents definition editor can save a linked project through `PUT /api/agents/{id}` with unique Linked project names. Saving it tags this agent's Runs for filtering and does not grant coding, Git or repository access. Selecting a project does not Enable or Run now. Audio and avatar retries stay unpublished. No Python or Host Runner changes. Restore, image rollout and LAN publish remain unpublished. Live preview `:8765` is an older image and was not used as evidence. Claude Code remains untested and unavailable.
