# Select a model, then send

Chat, the immediate entry and General preferences use a selection-only local
model picker. Choosing an installed GGUF saves the selection without starting,
stopping or configuring a runtime. GPU/context/runtime operations remain in the
dedicated model controls. Existing local-server model choices remain available.

The first consumer of a discovered GGUF can now enqueue an owned llama.cpp load
without requiring an earlier manual load. It uses a saved curated GPU/context
preset when present; otherwise devices are discovered through the private Runner,
with a modest 4096-token Chat profile. CPU-only discovery is supported. Failed
device discovery produces an actionable error rather than guessed device IDs.
Existing runtime presets and Coding's larger fitted Q8 context policy are retained.

Selection validates a present language-model GGUF and returns a pending endpoint
reference. Sending creates the normal load prerequisite and completion Run in
the same transaction. Concurrent conversations share an already-pending load;
they do not each launch a model process. Unknown runtime ownership still requires
inspection. External runtimes and models are not stopped, changed or downloaded.

Normal tests cover first selection without work, initial load on Send, shared
pending loads, saved CPU presets, missing Runner discovery and existing lifecycle/
Coding behavior. The selection-only UI exposes no required GPU/context form and
submits no load request when choosing a first-use file.

Real acceptance on 2026-10-14 used the existing Qwen3.5-9B Uncensored Q6_K GGUF in
a fresh isolated metadata database with the actual private native Runner. No prior
RuntimeInstance existed. The first Send created a load on discovered GPU 0 and 1
at 4096 context, followed by a successful local reply. Replaying the request reused
the Run. The owned runtime was then stopped through the typed lifecycle. Model
files and unrelated services remained unchanged. This proves that specific Chat
autoload path, not every model/context combination. Evidence:
`data/acceptance/auto-model-20261014`.

This delivers the local selection/autoload part of the
[conversation experience plan](plans/chat-work-experience.md). Further work unifies
provider/model selection and refines transcript/artifact presentation and verified
reasoning controls.
