# Ordered reference composition while a text model is busy

The real WORK-005 request asked to put the person from the second selected
picture into the scene from the first. Inspection of its persisted Run shows
that the assistant selected `chat`, then tried local Vision. Vision tried to
replace a text-only runtime that had another active consumer and correctly
refused. Thus this failure is not evidence that image admission itself needs to
stop active work: the requested Recompose operation was never enqueued.

Recognize direct placement/composition instructions on explicitly selected image
inputs, including English and Polish. Preserve reference order and existing
one-image Edit / multi-image Recompose contracts. Passive Web does not force
search. Advice, quoted instructions, code changes, agent goals, explicit selected
tools and absent image input do not authorize a media action. Reuse the existing
PhotoPipe Task child, permissions, translation and source snapshots, GPU queue,
owned-idle eviction, Stop and recovery. Never stop an active or external runtime.

Qualify the exact ordinary two-reference request with a busy text consumer,
confirm no Vision load/stop or unrelated inference was queued, then exercise
resource waiting/cancellation and a real two-reference result through the UI.
This increment does not claim to fix external GPU-memory pressure or the
separate busy short-context coding upgrade.
