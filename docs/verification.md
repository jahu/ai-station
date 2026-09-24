# Verification record — 2026-09-24

## Automated checks

- Backend and Host Runner: 142 pytest cases passed; Ruff lint and formatting passed.
- Frontend: ESLint, strict TypeScript, four UI behavior tests, and production build passed.
- Production Docker image and both Compose configurations validated.
- Production and development Docker deployments (including the Vite proxy): native Unix-socket telemetry, API health, worker execution through a fake executor, SSE replay, persisted history after API container restart, and supervisor cleanup passed.
- Image Docker/browser smoke: Generate → Library → Edit passed using a Pillow-only fake pipeline; source reuse and artifact rendering were checked. The initial browser run timed out on Edit; a second run passed. No real model inference was performed.
- Chromium: desktop dashboard, command palette navigation, run timeline, and mobile overflow checks passed with no page errors. Desktop and mobile screenshots were inspected.

## Actual workstation observations

Docker Engine 29.1.3 and Compose 2.40.3 are available. Two NVIDIA GeForce RTX 3060 GPUs (12 GiB each) were enumerated by `nvidia-smi`; live metrics were read through the native runner into the containerized API. These observations are not architectural assumptions.

The existing photo Python environment, photo pipeline, stable-diffusion.cpp executable, and image/LLM/video model roots are present. The original photo pipeline matches `reference/photo_pipe.py` and was not modified. Codex and Cursor executables are on PATH; Claude Code was not found. Open WebUI is already running in a separate Docker project and was left untouched. Model-server reachability/authentication has not been verified.

## Not tested / unavailable

No real image generation/edit/recompose/upscale, coding agent task, or local/cloud model completion was executed. The image adapter is enabled and verified against a Pillow-only fake pipeline in all five mode/backend combinations. Tests cover source lineage, image delivery, thumbnails, complete stdout/stderr chunks, lost dispatch responses, disconnected polling, cancellation during dispatch, permissions, unknown exit codes, retries, and the actual reference CLI parser. Chat/coding/agent adapters remain unavailable. No driver, CUDA, model file, existing AI script, or unrelated service was changed.

The frontend build currently reports a bundle-size advisory; this is a local application with a 241 KiB gzip initial JavaScript bundle. The TestClient dependency emits a Starlette/httpx deprecation warning; tests pass. Neither warning is suppressed.
