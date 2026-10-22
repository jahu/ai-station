# Continue from an image result

In Chat or Work, a direct follow-up such as `Powiększ to`, `Upscale the previous
image`, `Opisz tę grafikę`, `Zmień ten obraz: dodaj kapelusz` or `Ożyw ten obraz: spokojny ruch kamery`
can reuse a completed generated image in the same conversation. `Animate it into
a 5 second video` uses the normal long-video duration contract. Sending creates
a new ordinary Task/Run, retaining source-artifact lineage; it never overwrites
the previous result. The sent message displays the chosen image and an Inspect
source link. Generation still happens in the worker and remains cancellable.

Resolution runs before intent enqueue, only for explicit referential commands
with Auto action and no conflicting selected input/tool/research scope. Explicit
attachments and existing coding-task bindings take precedence. Ordinary Web
availability does not block media references or selected non-research media tools;
the effective media request has Web off without changing the composer preference.
An exact search query or explicit JavaScript request remains a conflicting scope.
A disabled saved query does not become an active research grant. General discussion,
negation, implicit pronouns in arbitrary text and a bare `Upscale` do not select
an old image. The selected provider is not changed and no external permission is
inferred. The existing Chat/Work capability policy still applies.

Only the most recent eligible image-result message among the last 32 assistant
orchestration messages is considered. Its image producers must belong to this
conversation and Task. Internal media frames are excluded. In a generation →
upscale chain, source/derived lineage selects the final image. Multiple independent
results require explicit Use in next prompt instead of a guess. A trashed or
unsuccessful latest result is rejected without silently falling back to an older
one. An image task that failed without publishing any image also blocks fallback.
A generic **Describe it** inspects pixels only when the current result is the
image; it cannot reach past a newer text answer to inspect an old picture.
Uploaded sources by themselves are not generated results.

The resolved artifact/message/producer IDs are stored in user-message metadata,
and the source IDs are snapshotted in Run parameters. First-Send receipt hashing
continues to use the original request; replay returns the original receipt before
resolution, even after newer images exist. Invalid/missing references return a
readable 422 before persisting a new message, Run or receipt. No schema migration
is needed. No model-selected artifact ID is accepted.

Normal tests use real temporary image uploads and simulated completed producers,
checking isolation, lineage, rejection, exact downstream image dispatch and receipt
replay. They do not run GPU generation. Real integration evidence is recorded
separately under application-owned `data/acceptance/`.
