# One-send recording questions

In Chat/Work, attach a recording and ask to summarize, translate, explain
or answer a question about it. Auto routes that explicit text intent to a reviewed
`audio.analyze` action. Explicit transcription stays CPU-only without an LLM;
read-aloud and portrait instructions keep their existing voice-reference rules.

The existing orchestrator creates one ordinary transcription child. Only its
confirmed successful completion publishes a normal Chat child on the same Task,
using the original user's instruction and the checked source reference. Publication
is atomic with the transcription result; there is no waiting worker, duplicate
execution architecture or polling HTTP handler. The response model is prepared
only after valid transcription, avoiding unnecessary model loads for invalid audio.

Provider/model settings are captured on Send. Later stages cannot gain external
AI permissions or silently follow a changed provider endpoint. Raw audio stays
in the native CPU runtime; only transcript text reaches the selected response
provider under normal Chat permissions. Quoted audio instructions are source data,
not commands or additional tool grants. Reply context reserves space for the new
bounded transcript and retains source/hash/truncation provenance.

A response-preparation failure is a separate inspectable failed stage and preserves
the successful transcript. Task Stop prevents later publication and uses existing
owned process/stream cancellation. Retries and worker recovery remain conservative;
uncertain work is not replayed. The one-send receipt remains idempotent.

The composer accepts common recording formats directly in Auto/Analyze/Transcribe
without making users select a voice-cloning workflow. Speech/portrait references
remain short PCM WAVs. Supported PCM widths are preserved when broadening the
recording uploader, with sample and decoder bounds unchanged.

Acceptance: fake-provider graph, permissions, no-early-model, failure, Stop,
publication replay and changed-provider tests; normal frontend checks and actual
CPU plus local-LLM summary of the already-approved recording. No cloud usage or
large model downloads are implicit.
