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
