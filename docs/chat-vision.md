# Local pixel vision in Chat

Image inspection uses an ordinary assistant Task with runtime-load and Chat Runs. The existing installed GGUF and its unique colocated `mmproj` companion are selected from the read-only registry; the chosen model and local execution are recorded in the Run. No downloads, cloud fallback or external-process changes are allowed.

The private Host Runner validates both discovered files and mounts each read-only into its owned llama.cpp container. GPU selection is dynamic. Context fitting reserves the projector's weight storage. A dispatched runtime's model/projector identity is immutable and recovery must preserve its exact request.

The worker resolves only explicit image artifact UUIDs in application storage, checks file/type/size boundaries and creates bounded inline image inputs. The multimodal Runner operation accepts only inline validated image data, never image URLs or caller filesystem paths. Image bytes are transient transport, not copied into Run parameters, logs or planner history. Current-turn images grant inspection only; image instructions cannot grant coding, publishing or tool permissions.

The existing Chat streaming/cancellation/recovery contracts remain authoritative. An inspection may load an owned vision model; canceling the answer does not kill a shared warmed model. No image-generated instructions are automatically executed.

Source: [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Fake transport, permissions, path boundaries, cancellation and projector identity are tested. Frontend checks and a real image understanding smoke test passed for the installed model/projector pair; see [verification](verification.md).

## Using it

In the default Platform assistant, click **Add images**, upload or choose a Library image, and send “Describe this image” / “Opisz obraz”. Alternatively select **Inspect images** in the compact Action picker. Attach up to four PNG/JPEG/WebP artifacts. Editing, recomposing and upscaling continue to use their existing actions.

AI Station prefers the conversation's model when it has an unambiguous installed projector; otherwise it selects an installed compatible pair. It reuses an owned vision runtime or queues loading at 32768 context on dynamically observed GPUs. An idle text-only instance of that same model is upgraded through ordinary stop/load Runs; active consumers prevent unloading. The selected local model appears in the response and Run details. A rejected dispatch rolls back its model-operation children.

Source PNG/JPEG/WebP images up to 20 MiB and 16 megapixels stay unchanged. Preparation respects EXIF orientation, composites transparency against white, and bounds image dimensions and payload size. The saved Markdown description links to all source artifacts; encoded image data is never persisted in Run parameters or events.

## Real acceptance — 2026-10-13

An explicitly opted-in smoke test used an isolated temporary control-plane database and private native Runner, with the existing Qwen3.5 9B Q6_K and BF16 mmproj files mounted read-only. A standard assistant request queued a model-load Run and a Chat vision Run. The local model correctly identified a red circle on the left and a blue square on the right in a synthetic image named `input.png`; its response persisted with source lineage. The test-owned runtime and Runner were stopped afterward. No model or image download, external AI, driver change or unrelated runtime stop occurred. The preview's idle AI Station-owned Q4 model was explicitly unloaded for GPU capacity.

Local evidence: `data/acceptance/chat-vision-20261013/`. This confirms this installed model/projector pair and basic pixel understanding; it is not an accuracy benchmark for arbitrary images or proof of every multimodal model.
