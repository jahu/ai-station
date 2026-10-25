# Managed memory embeddings readiness

Operator finding, 2026-10-25: Memory has no configured embedding model. Read-only
inspection confirms there is no `memory_embeddings` setup and no discovered
embedding-model candidate. FTS works; semantic retrieval is not currently ready.
The existing optional endpoint form is insufficient for the intended happy path.

## Required behavior

Memory offers a clear local setup path: select a suitable installed embedding model
or explicitly prepare a small recommended local model, check it, index memory and
perform semantic search. Manual endpoint/model input stays advanced configuration.
Display model, readiness, indexing coverage, progress/errors and execution location.
Do not silently point embeddings at the chat model or claim FTS is semantic search.

Prefer a separate owned CPU-only embedding runtime using the existing typed
llama.cpp/native lifecycle and private socket. Inspect installed capabilities and
verify current upstream embedding/model requirements before choosing a pinned,
publicly available multilingual model. It must work for Polish queries without
cloud credentials and have an explicit bounded download/footprint. No implicit
large downloads, external-runtime mutation, GPU-chat eviction or driver changes.

If CPU embedding support requires extending that lifecycle, add a typed embedding
purpose, fixed validated arguments and an embedding-only proxy. Keep chat/vision
requests unchanged. Model preparation, health, indexing and search use ordinary
Tasks/Runs/events/artifacts with permissions, deadlines, cancellation and recovery;
HTTP handlers only enqueue. Files remain inside configured/app-owned roots.

Reuse current vector validation, content hashes, stored model identity/dimension,
scope checks and cosine retrieval. Changed model/settings invalidate the appropriate
index. Updates, disabled/deleted memories and scope boundaries must not leak stale
or unrelated results. Do not pass credentials to models or normal API responses.

## Acceptance

Test typed configuration, actual endpoint/vector health, indexing, semantic query,
model/settings changes, stale vectors, scope filtering, stop/recovery and setup UX
with fixtures. Real qualification must produce nonzero vectors and meaningful
Polish semantic matches from an actual local embedding model, survive restart,
and prove that the existing chat container/context/GPU allocation were preserved.
Then qualify the Docker/native deployment and include these journeys in the
[operator QA workbook](operator-qa-handoff.md). Implementation is pending; ordinary
FTS remains available during setup/failure.


## Implementation decision (2026-10-25)

Use a container CPU executor backed by ONNX Runtime and the pinned quantized
multilingual-e5-small export, rather than extend native chat-runtime ownership
for this small encoder. This remains the existing Docker/native architecture:
CPU inference uses only app-owned model files inside the worker; no host access,
GPU, extra HTTP server or chat-model lifecycle changes are needed. The native
llama.cpp path remains available for generative models; manual compatible
embedding endpoints remain an advanced option.

The researched GGUF candidate explicitly mentions a custom inference fork; its
stock llama.cpp compatibility is unproven. The selected ONNX export is directly
supported by the CPU runtime and has about 136 MB of weights/tokenizer files.
Reference: [model export](https://huggingface.co/Xenova/multilingual-e5-small),
[original model](https://huggingface.co/intfloat/multilingual-e5-small),
[CPU thread controls](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
Pin commit, byte counts and SHA256 for every file. Downloads require an explicit
operator action and confirmation, use bounded public HTTPS with pinned DNS and
atomic verified installation; startup/index/search never download weights.

Each inference Run owns a bounded CPU subprocess, fixed two-thread profile and
parent-death signal. Stop terminates only that child; worker death cannot leave
an orphan model process or silently replay an interrupted Run. Load once per Run,
stream bounded JSON requests/results, chunk full memory text at actual tokenizer
boundaries, apply query/passage prefixes and mean pooling/L2 normalization.
Changed model/endpoint/encoding identities invalidate vectors. Recheck memory
content/scope/enabled state, cancellation and setup revision before publication.
The existing FTS, provenance and inspector remain available. Show semantic results
inline with their exact scope and entry links; endpoint fields are advanced.

Implemented on the feature branch: managed CPU setup, pinned file verification,
automatic indexing, scope-bound inline results, settings/content race guards and
owned process Stop/parent-death handling. Tests include real ONNX Runtime inference
using a tiny synthetic fixture; that is not pretrained-model quality acceptance.
Operator consent and real pretrained-model qualification remain pending. The model
is not presented as ready before its actual probe succeeds.
