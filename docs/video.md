> Candidate reduced-RAM profile: [qualification and rollout state](plans/wan-memory-profile.md). It is disabled by default and must not be treated as production-ready from a successful short encode alone.

# Local general video

The workspace now uses [durable long-media jobs](long-media.md): 1–60-second
video plans, bounded continuation or independent shots, CPU composition, RAM-aware
admission and Task Stop/resume. A real 60-second continuous draft is qualified;
this does not establish every quality profile or simultaneous multi-GPU generation.
[The longer-term execution plan](plans/long-media-execution.md) tracks subsequent
120/300-second profiles and broader quality acceptance.

The adapter setup and short-window limits below describe the reused native stage
and compatible direct-Run API, not a duration limit on the current workspace.

The Video workspace offers text-to-video and image-to-video with an installed
Wan 2.2 TI2V 5B profile, alongside the existing portrait-and-speech workflow.
Each request is an ordinary Task → Run → Events → MP4 Artifact. The worker uses
the shared host-media reservation, dispatch journal, cancellation and recovery.

The native Runner starts a fixed AI Station job in a configured Python environment
and calls only the required built-in ComfyUI loaders, Wan latent conditioning,
sampler and decoder. It does not start a ComfyUI HTTP server, submit an arbitrary
node graph, import custom nodes or touch an existing ComfyUI service. Installed
runtime/model files remain read-only; application inputs, cache and output stay
under the data root. Model downloads are disabled. Configuration explicitly selects
the existing installation, Python, diffusion weights, text encoder and VAE.

Requests bound prompts, image inputs, dimensions, frames, steps, seed and CFG.
The image mode conditions on the first frame; results are silent videos.
Sampling follows the [official Wan 5B workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_5B_ti2v.json):
UniPC, simple schedule, shift 8 and a default of 20 steps/CFG 5. Managed
process-group ownership is reused for cancellation and stale-worker inspection.
The adapter remains unavailable without complete configuration. Normal tests use
fake jobs; real hardware verification is recorded below.

## Setup

Configure the native Runner with `AI_STATION_VIDEO_PYTHON` (an existing compatible
ComfyUI Python environment), `AI_STATION_COMFY_DIR`, `AI_STATION_WAN_MODEL`,
`AI_STATION_WAN_TEXT_ENCODER` and `AI_STATION_WAN_VAE`. The fixed profile expects
Wan 2.2 TI2V 5B diffusion weights, a compatible UMT5 encoder and the Wan 2.2 VAE,
all existing safetensors files. These are administrator-selected file references,
not caller-supplied paths. Canonical Hugging Face cache targets receive named
aliases only in the owned Run directory; originals remain unchanged.

If a compatible environment is missing, the optional
`./scripts/bootstrap-video.sh /path/to/existing/ComfyUI` installs that installation's
Python dependencies into `.tools/video-runtime`. Set its Python path in `.env`.
This explicit setup may install sizeable Python wheels; it never downloads model
weights, installs a driver, changes system CUDA or starts/stops external services.
Do not run dependency setup while a video job is using that environment.
Normal startup remains `./scripts/start.sh`. Missing configuration blocks generation.

Open **Video → Create a scene**, choose Text to video or Animate an image, add a
prompt and generate. The latter accepts one uploaded or Library first frame.
Format and duration stay visible; steps, seed, negative prompt and GPU are advanced
settings. Stop, MP4 playback, download and Library inspection stay beside the form.
The Run URL survives refresh. Existing speech-driven work is under Talking avatar
and the Avatars workspace. Library images offer Animate image without starting work.
The Platform assistant supports **Generate video** and explicit English/Polish
video-generation requests, with at most one first-frame image.

The profile bounds dimensions to 128–1280 (multiples of 32), at most 1280×704 pixels,
17/33/49/65/81 frames, 4–40 steps, CFG 1–10 and a bounded seed. The default landscape
is 1280×704, matching the model's native workflow; portrait and square formats
are also available. Videos use 24 fps and have no audio. CPU prompt encoding and
low-VRAM sampling use the discovered selected GPU. Decoding uses the built-in
VAE decoder and its memory-aware tiled fallback. Hardware and competing workloads
still determine execution time.


## Verification — 2026-10-13

The native process was exercised through the real queued API/worker/Runner path
in isolated migrated databases, using already-installed Wan weights and ComfyUI
revision `387f98aa` with a project-owned PyTorch 2.11 environment. No weights,
drivers, system CUDA or existing services were changed.

- Text → MP4: 1280×704, 49 frames, 24 fps, 20 steps, CFG 5; completed in 398 seconds.
- First-frame image → MP4: 1280×704, 33 frames, 24 fps, 20 steps, CFG 5;
  completed in 288 seconds with recorded source-artifact lineage.
- Both MP4s were fully decoded. First/last frames were visually inspected for
  coherent forest imagery and preserved first-frame composition; motion was
  measured across decoded frames. GPU reservations were released after success.
- Native cancellation after launch removed only the owned group, published no
  result, and reached canceled state. Normal tests also cover failure,
  permission/path rejection, missing setup/Runner, SSE, API restart and stale
  dispatch without replay, plus Assistant dispatch and inline output.
- The production frontend was checked at desktop/mobile sizes. Its player loaded
  and played the actual native 1280×704 MP4 with working controls, Library/download
  links and no JavaScript errors. Metadata GETs in that browser check were mocked;
  the browser did not submit a real GPU job.

Early 256/512-pixel exploratory samples showed visual artifacts and were excluded
from quality acceptance. The published workspace defaults to the model's native
1280×704 profile with the official sampling shift and the built-in VAE decoder,
including its memory-aware tiled fallback. Portrait/square formats and every
advanced parameter combination have not been separately hardware-tested.
Local evidence is under `data/acceptance/wan-video-20261013/` (not committed).
