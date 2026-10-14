# Automatic local coding model selection

Coding defaults to **Auto · local long-context model**. The model picker remains
available; opening and closing it preserves Auto, and selecting a GGUF performs
no inference. Model loading is ordinary worker execution after Start coding.
Work's local coding scope and Create project & build also offer Auto or the
conversation model. Old requests with explicit model names keep their behavior.

`GET /api/coding/auto-model` is a read-only recommendation. Auto uses present
language-model GGUFs, the current file size/mtime, discovered GPU capacities,
previous user-selected GPU allocation and observed trained-context metadata.
It requires a fitted allocation of at least 100,352 tokens. Unknown runtimes,
changed files, missing GPUs and insufficient trained/allocated context are excluded.
Successful load history is distinguished from estimated allocation. Proven coding
models are preferred, then larger qualified models; Auto never selects an external
provider, downloads weights or terminates external processes.

The queued coding request snapshots the actual model and selection explanation.
Existing owned llama.cpp preparation/loading handles resource admission and
context fitting. Before native coding dispatch, the worker requires that exact
owned runtime to be ready with at least 100k context on the selected GPUs. A smaller
actual allocation fails clearly before source is sent to inference; an old estimate
alone does not authorize coding. The actual context is recorded as a Run event.

If no qualified model exists, Auto explains what needs checking in Models. Explicit
manual selection remains available for a deliberately smaller/local-server context.
There is no silent switch to cloud AI or a smaller model.

Normal tests cover selection, changed-file and insufficient-context rejection,
GPU allocation, metadata-only preview, API snapshotting and dispatch against the
actual context. A read-only check against this workstation's current registry
selected an already-observed 131,072-token GGUF on both GPUs; it did not launch a
model or execute a new real coding task.
