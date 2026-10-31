# Guided image setup

This is the next NR-14 vertical slice after [managed speech](managed-speech-setup.md).
Deliver a fresh-installation route from reviewed sources to an ordinary Images
result. Preserve the working configured photo pipeline, original script and model
files. This plan does not mark a new image adapter operational.

## Source audit, 2026-10-31

The official stable-diffusion.cpp release archives include Linux CPU, Vulkan and
ROCm variants, but no Linux CUDA archive. Do not select the CPU archive merely
because the host is Linux. Its upstream build also publishes an official Linux
amd64 CUDA container. The audited immutable image is:

`ghcr.io/leejet/stable-diffusion.cpp@sha256:800ba95bf36cbb24dd6c4cf116bd0c9a319b7b0ff00e1111ad1a6ea76944c33d`

The manifest and config hashes were checked directly against the public registry;
14 compressed layers total 1,863,360,483 bytes. Image labels bind source revision
[`e239e4b`](https://github.com/leejet/stable-diffusion.cpp/tree/e239e4b0fd3de49834cec67031a44796ca465abc).
Its [CUDA Dockerfile](https://github.com/leejet/stable-diffusion.cpp/blob/e239e4b0fd3de49834cec67031a44796ca465abc/docker/Dockerfile.cuda)
uses CUDA 12.6.3 and Ubuntu 24.04; entrypoint is `/sd-cli`. MIT runtime source,
CUDA and base-system components retain their separate licenses. A manifest audit
or successful pull does not establish GPU inference or supported image modes.

The initial Qwen profile should reuse the known four-file pipeline shape:
diffusion transformer, quantized text encoder, vision projector and VAE. Public
metadata pins the following candidate sources:

- [Qwen Image Q4_K_M](https://huggingface.co/0xSojalSec/Qwen-Image-2.1-Uncensored-GGUF/tree/242be4d1f70cc26fa45773c452f81980ed656e2e):
  4,604,557,984 bytes; SHA-256
  `833439e91bc1152d28f37aa198c7f6f4218b7de95754c2f7a318a2422ab4b2f8`.
  The publisher declares the **Qwen Research License**, not MIT or Apache, and
  says these are unmodified upstream weights rather than an ablated fine-tune.
- [Official Qwen3-VL encoder/projector](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/tree/f982a07559d4a2f6c8744d840bf6fccab30eea96):
  Q4_K_M encoder 5,027,784,800 bytes, SHA-256
  `67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2`;
  F16 projector 1,159,029,824 bytes, SHA-256
  `ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38`.
  Publisher metadata declares Apache 2.0.
- [Original upstream VAE](https://huggingface.co/Qwen/Qwen-Image-2.1/tree/b3179ad355be050328e483a9dfdd9e60cd62adfa/vae):
  1,350,989,512 bytes; SHA-256
  `a07a1b7c4ee2966a1b3bdc37de9b4f983d56937e46619f709a80b6e490675417`.
  The workstation's existing converted VAE is 675,509,688 bytes. It is a distinct
  object: do not use its filename or working result to claim qualification of
  the larger published object. Confirm actual supported VAE precision and memory
  behavior through the pinned CLI before fixing the recipe.

Existing workstation files may seed an isolated qualification store only after
full SHA verification, without renaming, changing modes or linking writes back
to the originals. The user declined another Qwen weight download; reuse matching
existing transformer/encoder/projector bytes for qualification. Preserve the
separate proof of what was actually downloaded versus reused. The upscaler is a
separate companion/source/license to qualify before declaring Upscale ready.
Private source evidence: `data/acceptance/guided-image-runtime-20261031/`.

## Implementation contract

1. Inspect the pinned image's actual CLI and CUDA behavior. Build argv from those
   observed flags, never guess options from another sd-cli version. Bind exact
   model/runtime inputs and normal Generate/Edit/Recompose parameters. Preserve
   existing style/profile behavior through repository-owned templates; never
   import or rewrite the external working script as part of installation.
2. Extend the reviewed bundle primitive to image metadata and all required
   companions. Keep canonical immutable relative storage, aggregate progress,
   unchanged-manifest Resume, live administrator authority and claim-epoch fences.
   Register shared model facts only after the full set verifies. No model loader
   executes during download, and no file receipt claims runtime readiness.
3. Prepare the fixed image through the existing native runtime installation
   lifecycle. Requests accept a built-in profile/fingerprint, not a Docker image,
   command, destination, mount or registry URL. Do not replace configured images.
4. Add a typed, owned **container job** for this fixed image capability, reusing
   the existing native container ownership/journal conventions. A Run UUID binds
   immutable image ID, request hash, allocated GPU, frozen input observations,
   app-owned output and absolute execution deadline before create/start. Mount
   only individual verified inputs read-only and the private output directory;
   use the host user's UID, no network, read-only root, dropped capabilities,
   bounded RAM/zero swap and PID count. Never pass the Docker socket to the job.
5. Container ownership is independent of the Docker CLI client's PID. A killed
   client or native restart must not hide a live GPU workload. Inspect verifies
   exact container ID, station/request labels, image, mounts and state. Stop is
   durable before dispatch and serialized with start; SIGTERM/grace/SIGKILL
   targets only that verified owned container. Release Run resources only after
   the container and any native supervisor child are confirmed gone. The job
   must enforce its fixed deadline inside the container even if its client dies.
   Keep completion/log receipts durable before any owned-container cleanup.
6. Reuse normal PhotoExecutor/Run/Event/Artifact contracts. Lost responses and
   worker restarts reattach the same container; they never repeat inference.
   Private source/PNG verification precedes publication. Capture actual CUDA
   placement and memory behavior, and report any permitted CPU placement clearly;
   do not present silent CPU fallback as GPU qualification. Record container
   execution and actual allocations in the normal inspector.
7. Existing explicit photo Python/script configuration retains priority, including
   incomplete settings that require repair. Otherwise resolve only an explicitly
   adopted, qualified managed image profile. Do not invent host paths for
   app-owned model records. Existing model choices/defaults/retries retain their
   historical snapshots and cannot silently switch to a new recipe.
8. Add a consistent Models setup card and Images empty-state link: measured
   hardware fit, disk/source/component licenses, saved history/progress,
   Stop/Resume, then an actual first result in the existing saved Images workspace.
   Model files being cached is distinct from runtime installation and inference.
   Keep unsupported modes unavailable rather than displaying a successful setup
   for missing Edit, Recompose or Upscale companions.

## Activation gates

Normal temporary-database/fake Docker tests must cover typed validation, canonical
paths and symlink escapes, modified inputs, account A/B history/receipt/media
privacy, shared model facts, immutable idempotence, canceled-before-create,
create/start lost acknowledgements, helper/client death with a live container,
Runner restart, worker lease/claim replacement, Stop after recovered queueing,
deadline enforcement, failed/partial outputs and exact owned-container stopping.
No test may kill an unrelated process/container or use real models by default.

Explicit real qualification must demonstrate the fixed GPU runtime, complete
verified inputs, Generate, a neutral structural Edit, one/multiple-reference
Recompose and qualified Upscale, with actual memory/time observations and owned
Stop/recovery. Exercise the whole new-account wizard/API/separate worker/native
path, navigation/restart history and the compiled desktop/phone UI. Match final
image/native package sources to the reviewed head. Preserve existing configured
integration and production data during a separate reviewed rollout.

This image slice does not remove the remaining music/video/avatar recipes,
semantic-memory setup, broader source discovery or actual Linux/Windows/macOS
consumer install/update/data-preserving uninstall requirements from NR-13/14.


## Current candidate evidence

The pinned image was actually pulled and its CLI was executed under non-root,
read-only-root, no-network, dropped-capability, PID and RAM limits. CUDA device
enumeration detected both workstation GPUs; no image weights were loaded. The
three existing transformer/encoder/projector files passed full SHA comparison
against the pinned publishers, so another copy from the network is unnecessary.
The existing VAE remains a distinct converted object. Existing owned llama.cpp
is currently occupying the GPUs; source/command work does not stop it.

The internal, unregistered `managed_image_command.py` binds Generate/Edit/Recompose
to fixed container coordinates and one/two allocated logical CUDA devices. It
retains prompts as single literal arguments, validates source counts and bounded
parameters, and cannot accept images, URLs, output paths or GPU strings supplied
by a caller. Its 21 normal cases pass. The candidate JSON recipe retains
`qualified=false`; it is not exposed as a ready model/runtime or installation.
The observed CLI supports explicit module placement, parameter placement, VAE
precision rules and multiple reference arguments. Actual inference, memory fit,
container ownership/cancellation/recovery, publication and guided UI remain the
required next implementation, not claims derived from `--help` or these tests.
