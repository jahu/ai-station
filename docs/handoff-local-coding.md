# Handoff: Local AI coding failure and GPU-fitting long context

Updated: 2026-10-08. Read this before continuing. The user explicitly requested a handoff for Cursor or Claude Code. Preserve the current implementation; do not restart the project.

## Immediate objective and latest user direction

1. Diagnose and fix the failed Local AI website task in the new project.
2. Retry that task in its existing owned worktree and verify real generation, not just fake tests.
3. Local coding needs a large context, initially requested at least 100k tokens. The latest clarification takes precedence: the model must fit in the existing GPUs and use the largest practical, stable context for complicated coding work. Do not blindly force 128k if it does not fit. Do not silently spill model layers to CPU/RAM or claim 100k support solely from a model's advertised capacity.
4. Preserve good UI/UX and avoid unnecessary work/token expenditure.

User has already authorized feature branches, pushes, PRs to develop, local validation in place of hosted Actions, reviewed squash merges, and restarting/upgrading AI Station while preserving data. Never push/merge main/master. Do not touch external services, drivers, model files, or the original photo pipeline. Read AGENTS.md and architecture/security docs. No additional permission is needed for routine project-only work or the local retry requested here.

## Git and deployment state

- Branch: `fix/local-coding-output-budget`.
- Open PR: https://github.com/jahu/ai-station/pull/48 (base develop).
- Commit `9aa0ecc`: tested output-budget fix, pushed; NOT merged/deployed.
- Additional long-context changes are a WIP checkpoint accompanying this handoff. They are NOT validated or deployed. PR is being marked draft for handoff.
- Latest deployed/develop commit: `ba0e766` (#47), in isolated worktree `.tools/ui-coding-local-picker`.
- Live UI: http://127.0.0.1:8765/#/coding
- Compose project: `ai-station-preview`; data: `data/preview`; DB: `data/preview/db/ai-station.sqlite`.
- Native runner: `data/preview/runtime/runner/runner.sock`.
- Root checkout is not the running release; changing its code does not update preview.
- #46 added name-only project creation (owned folder, Git, offline venv), Coding conversations/followups in the same worktree, automatic file discovery, model catalogs, sidebar history. #47 made the unified llama.cpp/Ollama picker visible directly in Local AI.

## Confirmed incident/root cause

User prompt: build a modern Polish/English website for Kora Timber, referencing https://www.koratimber.com/.

- Task: `8ad5c7a3-68f5-4cb2-9942-8c3d3fd64cab`.
- Project: `78233abc-3801-41a9-a4aa-3cb13b9ec8e2`.
- Failed proposal: `5bc70475-7593-4209-9931-cacb4540ffb5`.
- Worktree preparation: `d8a6dcbe-dd4e-45c7-8d84-e5b25ed3caec` (succeeded).
- Worktree ID: `54a6938d-2145-47d5-8305-d90ba2416e2f`.
- Worktree path relative to data: `worktrees/78233abc-3801-41a9-a4aa-3cb13b9ec8e2/d8a6dcbe-dd4e-45c7-8d84-e5b25ed3caec`.
- Model key: `llamacpp:7d9156d7-1ffb-481a-925c-6a3988ee099d`.
- Runtime: `f2cb7dd3-84ce-4d1a-89c8-71f9b33c2054`.
- Owned container: `ai-station-llama-f2cb7dd3-84ce-4d1a-89c8-71f9b33c2054`.
- Load Run `24720956-01f8-4bed-a9af-03b4fa06d957` succeeded on GPUs [0, 1].

Run events show source discovery succeeded: list_files found README.md, then the model selected index.html, style.css and script.js. Final code generation failed with `Local coding response was truncated or requested a tool`.

Root cause is in `host-runner/ai_station_runner/local_coding_job.py`: every completion, including the full three-file proposal, had `max_tokens=2048`. The owned llama.cpp logs confirm EXACTLY 2048 generated tokens, 122.1 seconds, ~16.76 tokens/s. This is an output budget failure, not a model-loading/GPU crash. Complete-response validation prevented partial writes. Verified none of index.html/style.css/script.js existed afterward. Run metadata confirms process gone. The original failed Run must remain as audit history.

## Tested output-budget fix (commit 9aa0ecc)

- Proposals request 8192 output tokens; short exploration retains 2048.
- Streaming wall-clock limit 900 seconds; whole owned job alarm 1200 seconds; idle HTTP timeout stays 300 seconds. Cancellation/ownership unchanged.
- Progress logs every ~10 seconds report generated character counts without exposing incomplete source.
- `finish_reason=length` produces a specific output/context-limit message and states no proposal was applied; tools and other non-stop completions still fail closed.
- Added fake-provider regression respecting an output cap, generating multiple complete files beyond the old 2048-token budget; checked no writes on truncated responses.
- Documentation: `docs/local-coding.md`.

Validation before long-context WIP:

- `./scripts/check.sh`: **472 passed, 5 skipped**, lint/format pass. Log `/tmp/ai-station-coding-budget-check.log`.
- That suite started before adding the extra large-output test. Then ran the new regression plus both truncation/tool tests separately: **3 passed**. Log `/tmp/ai-station-coding-budget-regression.log`.
- Ruff lint/format checked final budget test/source files again.
- Docker image built: `ai-station:coding-budget-reviewed`, ID `1703e94b8478`. Log `/tmp/ai-station-coding-budget-image.log`.
- Frontend was unchanged at this checkpoint; #47 had 55 frontend tests plus lint/typecheck/build green.
- No real retry has been executed with the fix yet. DO NOT claim success for the actual website task.

## Hardware/model findings, measured locally

Existing model: Qwen3.8-27B-RVN-Uncensored / RVN-Q4_K_M-multilingual.gguf, ~15.4 GiB weights.

Read-only metadata from the owned server's `/v1/models`:
- `n_ctx_train`: **262144** (advertised/trained context).
- `n_ctx`: **4096** (actual current runtime context).
- model parameters: 26,895,998,464.
- runtime build: `b11011-aa39d7a3e`.

Measured with the model idle at context 4096:
- GPU0: 12288 MiB total, 7938 used, 3975 free.
- GPU1: 12288 MiB total, 8952 used, 2958 free.
These are momentary values, not architectural constants.

Installed image: `ghcr.io/ggml-org/llama.cpp:server-cuda`, existing image only; do not pull/download. Its `--help` was inspected by a temporary `--rm --network none --read-only` container without loading a model. Supported flags:
- `--ctx-size`, `--cache-type-k q8_0`, `--cache-type-v q8_0`, `--flash-attn on`.
- `--fit off` prevents automatic adjustments; existing runtime already specifies `--gpu-layers all` for GPU use and layer split across selected GPUs.
- Full help saved at `/tmp/ai-station-llama-help.txt`.

Candidate: 131072 context + Q8 KV cache, both GPUs. **NOT yet loaded, VRAM fit NOT verified**. Do not confuse startup allocation with successful long-prompt inference. If 128k fails or leaves too little headroom, choose a measured smaller context or more suitable installed model according to the user's latest clarification. No download authorization is implied.

Read-only server inspection can use httpx HTTPTransport over:
`data/preview/runtime/llama/<instance-id>/io/model.sock`
with base_url `http://llama`, endpoints `/v1/models` and `/props`. Avoid dumping `/props`' large chat template; select only relevant metadata. Container logs are owned-project logs only.

## Long-context WIP: review and finish before shipping

Modified files:
- `backend/app/llama.py`
- `host-runner/ai_station_runner/llama_runtime.py`
- `frontend/src/pages/LlamaModels.tsx`
- `frontend/src/pages/Coding.tsx`
- `docs/local-coding.md`

Current draft behavior:
- Load schemas allow up to 262144 context, add typed `cache_type` f16/q8_0 (default f16 for compatibility).
- Backend persists cache type in instance metadata/load parameters.
- For `local_proposal`, `prepare_consumer` requests at least 131072. If an existing smaller owned runtime is idle, queue stop -> load -> coding dependencies, preserving GPU selection and using q8_0. Other active consumers cause an explicit conflict instead of being interrupted. Existing pending load must finish before stop.
- Reloads preserve context/cache preset; a smaller stopped preset upgrades for Coding.
- Native q8_0 load adds K/V q8_0, Flash Attention on, fit off. Legacy manifests lacking cache_type compare as f16 on replay without changing recorded ownership digest.
- Shared picker has a `coding` prop; first Coding load defaults to 131072 and q8_0. Chat retains 4096 default. Context field upper bound raised to 262144.
- Coding explanatory text mentions 128k/Q8; revise this if adaptive fit selects another value.

Only formatting has run on these WIP changes. No tests/build/real hardware acceptance yet. Important remaining review points:
1. Latest user asks for GPU fit/max practical context, so the hardcoded 131072 upgrade is only a candidate, not a finished adaptive policy. Consider a persisted configurable Coding context target informed by measurements; avoid retrying a known impossible allocation indefinitely.
2. Native snapshot currently calls only `/health` and marks ready. It does NOT verify actual context, model supported context, or full GPU residency. Add read-only runtime metadata/verification if reporting these as guarantees; never claim an advertised 262k model is currently running at that size.
3. Existing external local server (Ollama) context is not upgraded/verified. UI says its context is configured separately. Do not silently claim 128k for qwen3:8b from that endpoint or reconfigure an unrelated service.
4. Context capacity does not remove current bounded code snapshots: ten paths, 32KB per file, 64KB total, bridge 128000 content characters. Do not claim 100k tokens of repository input are currently sent. Any expansion needs deliberate boundary/tests, not just the runtime setting.
5. Test concurrent consumers, queued/loading smaller runtime, stopped reload, already-large runtime reuse, dependency failure/cancellation, legacy manifest replay, GPU allocation and invalid schema values.
6. After new runtime prep, the original website Run may expose additional model-output issues. Resolve evidence-based failures rather than assuming the larger cap is sufficient.

## Next concrete steps

1. Inspect git diff and this handoff; finish/review the WIP. Add backend tests in `backend/tests/test_llama.py`, runner argv/schema/replay tests in `host-runner/tests/test_llama_runtime.py`, and picker coverage in `frontend/src/pages/LlamaModels.test.tsx` as appropriate.
2. Run required local checks. Because WIP changes backend/Runner/frontend, use `./scripts/check-all.sh` once the edits are complete. This includes Docker/Compose. Fix real failures. Do not rerun expensive inference unnecessarily.
3. Update PR #48 title/body around final scope. Review full diff and exact remote head; hosted Actions are manual per AGENTS. Mark ready and squash merge to develop only after successful checks.
4. Build/tag final image; old image `1703e94b8478` contains ONLY output-budget changes, NOT long-context WIP. Do not deploy it while claiming the context changes are present.
5. Deploy from a new isolated release worktree, preserve data and keep backup. Existing helper `data/acceptance/coding-budget/deploy.py` is prepared but NOT run. It expects old release `.tools/ui-coding-local-picker`, new release `.tools/ui-coding-budget`, and image `ai-station:coding-budget-reviewed`. Review/update it and verify no active Runs first.
6. Measure actual context/VRAM on the owned 27B runtime using the typed lifecycle. Retry the user's task through the existing conversation endpoint; do not edit the owned worktree directly or erase failed history.
7. Inspect resulting Run, files/diff, original checkout, and appropriate page/build checks. A generated website is not proven correct just because inference succeeded. Existing Coding has no web-fetch permission/tool, so do not claim it inspected the referenced website unless actually implemented/executed separately.
8. Report the real outcome, actual context and VRAM numbers to the user; document acceptance, residual scope honestly.

### Retry request (after validated deployment, inspect latest state first)

POST `/api/coding/sessions/8ad5c7a3-68f5-4cb2-9942-8c3d3fd64cab/messages`
with JSON fields `prompt`, `expected_run_id` (latest proposal, currently `5bc70475-7593-4209-9931-cacb4540ffb5`), `external_ai: false`.
Use the original task intent, not a new unrelated task. This retains Task/worktree and records the continuation. A model context upgrade can enqueue normal prerequisite Runs. Poll actual returned IDs; don't assume stale IDs are still latest if user has interacted meanwhile.

### Deployment procedure reference

The ignored helper verifies Compose labels/old workdir and the unique owned launcher supervisor; refuses active Runs; SQLite-backups and integrity-checks; terminates only that supervisor; tags the reviewed image; execs `scripts/start.sh --no-build` from the new release. Start helper via detached Popen with log under `data/acceptance/coding-budget/preview.log`. Do not run an attached deployment that disappears when the agent turn ends.

Create new release only when ready:

```bash
git worktree add --detach .tools/ui-coding-budget develop
ln -s ../../.venv .tools/ui-coding-budget/.venv
```

Prior visual acceptance/scripts are under `data/acceptance/coding-workspaces/` and `data/acceptance/coding-local-picker/`. They are local ignored evidence. UI preview is local-only. Root repo is `/home/jahu/AI/apps/ai-station`; shell sandbox currently often errors with `bwrap: loopback: Failed RTM_NEWADDR`, so previous work used approved project-only escalated commands.
