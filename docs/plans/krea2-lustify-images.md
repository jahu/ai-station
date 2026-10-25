# Krea 2 / LUSTIFY image backend

Operator goal (2026-10-25): finish the Qwen investigation, then add LUSTIFY v10
(Krea 2), ordinary image editing and identity-preserving recomposition, including
two references. Preserve Qwen/Juggernaut and provide a simple compatible-model
choice and editable presets. The later operator instruction authorizes reviewed,
locally qualified PR squash merges into `develop`. Qwen Q8 download was canceled;
the installed Q4 hash exactly matches the supplied repository's Q4 file.

## Runtime and model selection

Use a pinned, AI Station-owned ComfyUI runtime plus the author's V2 node pack.
The installed sd.cpp supports Krea 2 generation, but its generic reference
presets do not establish the complete V2 dual-conditioning/placement contract.
Keep the working photo pipeline untouched. Native runtime executables, source and
venv belong in a user-owned native-only directory outside control-plane mounts;
weights stay in a configured model root. Do not modify an existing ComfyUI checkout,
its environment, NVIDIA/CUDA or existing model files. Explicit development setup
may install pinned project components; normal startup/inference never downloads.

The operator subsequently required GPU-only execution (no weight/compute offload
to system RAM). The initial candidate is therefore LUSTIFY v10 Turbo Q4_0,
matching Qwen3-VL 4B FP8 encoder and Krea VAE, with Identity Edit V2 or General Edit
V2 r64 weights. The operator supplied both Turbo Q4_0 and FP8; both were verified
against the creator's exact SHA-256 and moved from Downloads into the configured
image diffusion-model directory. No duplicate checkpoint download was started.
Choose one LoRA
per operation. The primary Civitai metadata binds exact file IDs and hashes; a
public HF copy is usable only if its SHA256 matches the creator's file. Download
verification is atomic and resumable, with no overwritten unknown files. Qwen's
2.1 VAE and 8B text encoder are not substituted for Krea's companions.

[Author's nodes](https://github.com/lbouaraba/comfyui-krea2edit) specify both
image-grounded text encoding and source VAE tokens. Wire `target_latent` before
sampling to avoid repeated VAE-induced model offload. The
[V2 model card](https://huggingface.co/conradlocke/krea2-identity-edit) recommends
Turbo at eight steps / CFG 1, identity reference boost about 2 and general-edit
boost about 4. Reference layout is aligned for precise edits and optionally beside
for restaging; per-reference roles remain explicit. Show the model/LoRA license
links and actual personal/non-commercial V2 terms in model details. No commercial
permission is inferred by installing the weights.

## Shared execution boundary

An image request resolves an installed ModelDefinition and a per-operation preset;
freeze its exact model/files/profile in the Run before queuing. Reuse ModelFile,
ModelDefinition and settings storage; no second model registry. Defaults are
operator-controlled and versioned. An explicit unavailable model fails clearly;
no silent fallback. Legacy explicit backend callers and saved Runs retain their
existing behavior. Model/preset changes affect future Runs.

Krea execution extends the existing photo executor's host-media lifecycle, reusing Task → Run →
Events → Artifacts, resource reservations, managed process groups, Stop, leases,
recovery, source lineage, Upscale/video follow-ups and conversation results.
The native API accepts validated settings and model references, never arbitrary
workflow JSON, commands, scripts or external URLs. A fixed owned job directly
imports pinned Comfy nodes, following the existing Wan adapter; there is no Comfy
HTTP server or arbitrary graph API. This replaces the initially proposed per-job
loopback server with the existing simpler execution pattern.
Its children share the owned process group; cleanup confirms they are gone before
releasing resources. Existing external ComfyUI/services are never controlled.
Inputs/outputs are validated canonical app-owned paths; only verified final PNG
bytes become Artifacts. Job configuration, model aliases and runtime caches live
under the private native runtime's owned `jobs/<run-id>` directory, outside the
container-writable application-data mount. This prevents replacement of import
paths/configuration through shared storage. No container privileges, Docker socket
or unrestricted host mounts.

Use GPU-only execution on discovered GPUs. Place the diffusion model and auxiliary
encoder/VAE on separately reserved devices when required; never silently use CPU
inference, layer streaming or swap as a fallback. Ordinary file loading and process
bookkeeping still use system RAM. The pinned Comfy `--gpu-only` profile disables
CPU model offload; both load and offload devices must remain CUDA. Presets target
the observed 12-GiB class without hard-coding the machine or assuming both cards
are free. Reserve host RAM as well as all used GPUs. Record actual GPU/model/settings; do not
claim that fitting weight bytes alone proves inference fits. Editable resolution,
steps, CFG, seed, reference strength and layout retain validated bounds.

## UI and acceptance

Images gets a clear Model choice filtered by the operation, plus an ordinary
preset and advanced controls. Per-operation default selection is simple and
persistent; model/runtime paths remain in details. Model availability and actual
reference limits are visible before Send. Both new models and existing Qwen /
Juggernaut retain Library/Chat/Work/agent provenance and result inspection.

Normal tests use temporary databases and synthetic processes. Cover model/default
resolution, frozen settings, compatibility validation, graph binding, safe paths,
owned child cancellation/recovery, resource admission, artifact registration and
current conversation/follow-up contracts. Qualify desktop/mobile compiled forms,
full local checks, image/Compose and exact deployed source. Real opt-in acceptance
must generate actual LUSTIFY T2I, General Edit V2, single-reference Identity Edit V2
and two-reference recomposition, inspect output quality and actual memory use,
exercise Stop and preserve original files. Use neutral, fully clothed scenes; do
not replay explicit sexual instructions. Pending steps remain pending in reports.

## Setup and current evidence

The two explicit setup commands default to an offline, read-only plan:

```bash
.venv/bin/python scripts/install-krea2-companions.py --destination "$KREA_MODEL_DIR" --download
.venv/bin/python scripts/install-krea2-runtime.py --destination "$KREA_RUNTIME_DIR" --install
```

Use a dedicated model-root child for companions and a private native-only runtime
directory outside mounted application storage. The runtime installer fetches exact
source revisions, checks existing owned source and installs hash-locked wheels in
a separate Python venv. Neither command downloads LUSTIFY, changes `.env`, enables
inference, modifies an external installation or changes host drivers/CUDA.
Repeated companion setup preserves verified files, refuses changed/unknown final
files and retries only uncommitted downloads inside its owned manifest directory.

2026-10-25 development evidence: all four companions are downloaded and verified
(6,410,554,230 bytes); the owned pinned runtime and dependencies are installed.
Real runtime imports recognize both GPUs, V2 editing nodes and the GGUF loader;
queried load/offload device policies stay CUDA on each card. This is an import /
placement-policy check, not an inference success. The native typed adapter remains
disabled by default. Synthetic tests cover bounded options, hashes, paths, exact
LoRA choice, GPU bundles, owned process cancellation and restart inspection.
The actual Q4 file declares `general.architecture=qwen_image`, which the pinned
GGUF loader accepts; shape-only inspection of all 430 tensors detects Comfy's
`Krea2` class with 28 layers, without allocating model weights or doing inference.
Actual Q4 loading and all four required image cases now succeeded through ordinary
durable preview Tasks/Runs: Generate, General Edit V2, single-reference Identity
Edit V2 and two-reference Identity Edit V2. The inspected cases recolor a jacket,
restage a recognizable generated adult in a library, and combine a separately
generated cafe scene with that subject. Source IDs/hashes and final PNGs remain
in Library. Generic generative editing does not establish perfect pixel/identity
preservation or arbitrary object-removal accuracy; no explicit sexual prompts
were replayed. A real Stop requested during sampling canceled its owned process,
produced no artifact and released both GPU/RAM reservations.

For the measured 768×1024 two-reference case, peak PyTorch allocations were about
9.36 / 6.29 GiB; allocator reservations about 10.72 / 7.10 GiB, within the two
12-GiB-class devices. Full weight residency is checked on CUDA before text,
diffusion and VAE execution. Loader process RSS peaked around 9.92 GiB; normal
host file loading still uses RAM, so conservative admission now reserves at least
12 GiB host RAM plus the scheduler's existing headroom. This is not CPU inference
or weight streaming. Higher resolutions are editable within validated limits but
are not implied to fit by this measured profile.

Registry choices, versioned per-operation defaults, immutable Run model snapshots,
selected-Qwen checkpoint dispatch and the Images model/preset UI are implemented.
Model selection is at the top of the form; switching models preserves sources and
uses that model's settings. Oversized reference selections remain visible and must
be corrected before Send. Models links prepared image definitions to Images and
does not present llama.cpp context/cache controls for them. Library/Chat/Work
retain the existing `photo_pipe` execution family, avoiding a parallel engine.

The compiled desktop/mobile UI passed six actual API/worker/native synthetic-image
flows, including saved defaults and two references. Evidence is retained under
`data/acceptance/krea2-lustify-20261025`; real receipts are `scene-01.json`,
`edit-01.json`, `recompose-01.json`, `recompose-two-01.json` and `stop-01.json`.
Full local checks, PR review and preview deployment remain release gates. The
current live preview has not yet been upgraded to this feature branch.
