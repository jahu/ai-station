# Consumer-first setup direction

Owner direction, 2026-10-26: someone with a home GPU should be able to download,
install and use AI Station without knowing model servers, venvs or GPU flags.
Keep this separate from the current v0.0.2 manual Linux prerequisites. The
[next-release contract](next-release-0.1.md#installers-catalog-and-automatic-setup)
adds the explicit Windows/macOS/Linux, account-bootstrap and model-catalog gates.

1. Package a discoverable installation path. Check prerequisites and explain any
   missing component in plain language. Keep the Docker control plane/native
   user Runner boundary; do not silently alter GPU drivers, CUDA or unrelated apps.
2. Detect CPU, RAM, storage and actual GPU devices. Recommend tested compatible
   profiles with honest vendor/runtime support and enough memory headroom. CPU
   fallback and smaller models should be explicit choices, never hidden cloud use.
3. Offer capability-oriented setup: conversation, images, video, voice, music,
   avatars and agents. Explain the expected download size, disk space, licenses
   and known hardware fit before the user starts a download.
4. Add reviewed model/runtime downloads with provenance, verified hashes,
   progress, cancellation/resume and safe partial-file handling. Do not move or
   overwrite existing user models. Reuse compatible installations where possible.
5. Apply working presets and typed configuration through the existing control
   plane/Runner interfaces. The user should not have to edit .env for the normal
   path. Run real readiness checks; diagnostics must distinguish unavailable,
   misconfigured and ready rather than manufacturing a green status.
6. Offer a short first task and a clear result in the conversation/Library.
   Preserve full execution details for those who want them. Model refusal behavior
   follows the chosen model; compatible uncensored weights remain user-selectable.

Acceptance needs a clean-machine journey for each advertised hardware/platform
profile: install, download, cancellation/restart, first actual inference, artifact,
update and data preservation. Existing Linux/NVIDIA qualification is not blanket
AMD/Intel/Windows/macOS support. Each new integration must meet the same permission,
owned-process, recovery and storage contracts. This is planned work, not a claim
that a one-click consumer installer or automatic model setup already ships.

The concrete [guided installation contract](guided-model-installation.md) now
tracks the catalog/download/Runner adoption/onboarding/launcher sequence. Its
initial branch has an unpublished resumable, pinned-file primitive and verified
starter metadata; the end-user installation flow and platform qualification
remain required.
