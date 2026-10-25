# Image generation followed by Upscale

Images offers **Upscale result 4×** for Generate, Edit and Recompose. The Platform assistant offers the same option and recognizes an explicit final instruction such as “Generate an image of a forest, then upscale it” or “Zmień kolor, a następnie powiększ wynik”. That final instruction is removed from the generation/edit prompt. An ordinary mention of upscaling inside a scene does not add an operation. Other assistant actions cannot use the option to acquire image capabilities.

The initial request creates a normal photo Run. After confirmed successful process completion, the worker registers its image, queues one ordinary Upscale child and records the child ID in the same database transaction as completing the first Run. Both belong to the same Task and retain conversation provenance. The child inherits the effective permissions, GPU request and trigger; it consumes only the new artifact. There is no additional shell, generated command, model download or second execution engine.

Failure, cancellation, uncertain process completion and output-registration failure never publish a follow-up. A restart before the transaction commits cannot publish a half-finished workflow; after commit the normal queue contains the child. Expired leases do not blindly replay the first process. The native adapter and GPU reservations are unchanged. The first GPU reservation is released after confirming the process group is gone; the child obtains its own reservation. An idle owned LLM may be evicted through the existing scheduler, but external runtimes are never controlled.

`GET /api/images/runs/{id}/workflow` follows validated same-Task photo child pointers, including explicit retries, with a cycle/length bound. Images retains the original Run in its URL, displays the stages and shows the final artifact. Stop targets the current stage. If Upscale fails, retrying that stage reuses the saved original image; it does not regenerate. Both artifacts remain in Library with direct source lineage. The assistant's existing Task projection displays all stages and artifacts and treats a retried failed stage as superseded.

Fourfold Upscale retains the existing 64-megapixel bound. Generate/Recompose sizes already fit that bound; Edit with the option requires a maximum side of at most 2048. Standalone Upscale cannot request another automatic Upscale. The option is strictly boolean and off by default.

This is an operational sequential image workflow. Arbitrary generated multi-step plans and music creation remain separate work.


## Image → video

The platform Assistant offers Image → video and recognizes an explicit instruction
such as “Generate an image of a forest, then animate it: mist drifts between the trees”.
The image instruction and motion instruction stay separate in persisted parameters.
After confirmed image success, the same completion transaction queues one Wan
video Run whose first frame is the newly registered artifact. No child is published
on failure, cancellation or uncertain process completion. Both outputs retain Task,
conversation and source lineage; each stage acquires/releases its own GPU lock.

This bounded workflow starts without reference images. General image editing and
recomposition can use the typed image API's optional bounded video_prompt; it is
exclusive with automatic Upscale and is unavailable for standalone Upscale.
Missing video setup is checked before starting the workflow. Follow-up publication
is pure metadata work: runtime I/O remains outside that transaction.

Images follows validated photo/Wan child pointers after refresh and shows the
active stage's image or video result; Stop targets that stage. The Assistant shows
both outputs inline through its existing Task projection. The Wan child chooses
the matching native landscape, portrait or square format from observed image
dimensions. Advanced Edit follow-ups remain bounded to a 2048 maximum side.

## Real combined acceptance

On 2026-10-13 an explicit Assistant Image → video request in the live local
deployment completed one Task with photo and Wan Runs, retaining both Library
artifacts and the first-frame source lineage. Qwen generation took about 310
seconds; Wan produced a fully decoded 1280×704 MP4, 49 frames at 24 fps, in
about 378 seconds. Only an idle AI Station-owned llama.cpp instance was evicted
through its normal stop Run to make room; media resource locks were released.

This proves actual composed execution, persistence and video output. It does
not certify every prompt's visual accuracy: the existing photo pipeline appends
skin/face styling, and this forest instruction also produced an unrequested
portrait. That bias requires a prompt-only adapter profile without changing
the original pipeline. No claim of exact scene adherence is made for this sample.

## Prompt-only generation profile

New Assistant image generation and the Images workspace use the submitted prompt
without the pipeline's implicit skin/face photo styling. **Add portrait styling**
in Images restores that original profile explicitly. The raw image API keeps its
`pipeline` default for existing integrations; `prompt_style: "prompt"` selects
the new profile for Generate only. Edit, Recompose and Upscale retain their
existing identity and input contracts.

The Runner launches an app-owned wrapper using the configured photo Python. It
imports the trusted existing pipeline and clears only `PHOTO_SUFFIX` and
`T2I_NEGATIVE` in that owned process; the file on disk is unchanged. User-supplied
negative prompts still pass through the real CLI. Unsupported pipeline versions
fail explicitly. This is a fixed typed profile, without caller-selected scripts,
module paths or Python code. GPU selection, process-group ownership, cancellation,
recovery, offline operation and artifact paths reuse the existing photo executor.
The chosen style remains in Run and Artifact parameters.

On 2026-10-14 the prompt-only profile completed real Qwen generation through
the Assistant's search-informed workflow. The inspected empty-forest output
contains no people; the original pipeline hash remained unchanged. See
[search-informed acceptance](web-search.md#real-search-informed-image-acceptance).

## Researched first-frame animation

Image → video can optionally search the web before preparing its first frame.
The bounded sequence is search/local brief → prompt-only image → Wan animation,
with scene and motion instructions kept separate. Sources, the image and video
remain in one Task's history. Missing video setup is checked before research;
failed/canceled research or generation never publishes the next media stage.
Explicit Generate image stays a single image even if its description mentions
an animation; the selected action remains authoritative. Normal composed
verification uses fake providers/native jobs. The separately executed real
search→image and image→Wan acceptances do not claim a real combined four-stage
execution.


## Instruction-only editing

New Chat/Work edits and the Images workspace select `prompt_style: "instruction"`
for Edit and Recompose. The model receives the submitted edit without the legacy
identity/portrait paragraphs. The Images **Use classic identity template** checkbox
restores the original behavior; raw image API callers and previously queued Runs
retain their existing `pipeline` default. Generate and Upscale are unchanged.

The fixed native wrapper clears only the relevant constants in its own imported
pipeline module: `IDENTITY_PREFIX` for Edit, and `RECOMPOSE_PREFIX_SINGLE`,
`RECOMPOSE_PREFIX_MULTI`, `PHOTO_SUFFIX` for Recompose. This prevents an implicit
photo/skin-style request and avoids treating every reference as the same person.
There is no caller-selected Python code, module path, model path or shell. The
external script on disk, sampler, CFG, dimensions, model weights and source pixels
are unchanged. Unsupported pipeline/profile combinations fail explicitly. Profile
choice is frozen in Run and Artifact parameters; process ownership, Stop, recovery,
resource reservations and source lineage reuse the existing PhotoPipe executor.

Investigation on 2026-10-25 confirmed that both reported Recompose outputs used
Qwen Image 2.1 Q4_K_M with its matching VAE/Qwen3-VL vision projector, 30 steps,
Euler and CFG 6. The source artifact was the original Generate output in both
cases; no chained recompression or Upscale was involved. CFG 6 matches the
[upstream editing example](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/qwen_image_2.1.md).
The observed artifacts and ignored changes are not a proven CFG or GPU hardware
fault. Long implicit prompt templates are one tested adapter concern; actual
visual improvement must be checked with neutral edits before claiming success.
No explicit sexual prompt is replayed for qualification.
