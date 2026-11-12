# Revising Studio materials in the conversation

The completion audit found an execution gap: `studio.produce` always creates a
new material. Existing media aliases support reference reuse, but they do not
identify an editable storyboard or its parent revision. A follow-up must be able
to produce a real new version, without silently creating an unrelated film.

Capture a bounded local-only catalog of verified completed Studio results from
the same account and conversation. Give each material a stable opaque alias,
its visible revision, title, project and options. Keep ownership, current material
version, immutable revision fingerprint and actual export provenance private.
External providers receive neither this catalog nor Studio execution authority.
Model output can select only a captured alias; it cannot supply paths or Run IDs.

Extend the frozen Studio intent with an optional source-material alias and an
explicit inherited-project choice. Absence retains the exact old creation path.
An ordinary follow-up inherits its source's options and identity, applying only
declared overrides. A new parented revision in the same material retains all old
versions. A requested different brand creates a linked copy under that brand;
it must not move or overwrite the original project/material. Recheck owner,
archive state, captured version and parent fingerprint before initial dispatch.
The normal local director receives the actual previous storyboard and feedback.

Reuse completed visual takes only when their generation intent matches the new
shot and the verified clip window covers the new edit. Composition/caption edits
do not by themselves require new image inference. Ambiguous matches are not a
license to guess. Changed visuals use existing generators. Preserve source
hashes, original references, aspect fitting and native inspection.

Reuse narration and score only through explicit frozen provenance and unchanged
audio contracts. Changed words, performance, narrator or score cannot reuse an
incompatible take. A caption-only revision should not need six new voice jobs.
Existing full-production reuse keeps its legacy strict behavior until an
explicit revision-aware contract is qualified. No new execution engine, database
schema, native endpoint or permission is needed.

The same wrapper owns planning/production Tasks and forwards Stop through its
existing closed registry. Publication and recovery stay transactional and
idempotent. Return the actual material/revision/film links; a partial plan does
not fulfill a request for a revised film. Keep the capability unadvertised until
its dispatch, cancellation, recovery and provenance contracts pass tests.

Qualification: complete temporary-account ReAct flows for new/legacy behavior,
same-material revision and different-brand copy; stale/foreign/archived/trashed
sources; no external catalog leak; exact parent/history/settings preservation;
unchanged-source/audio reuse and changed-source rejection; Stop/recovery/no
duplicate publication. Then use one ordinary local-model conversation follow-up
with existing approved media and no unnecessary image/video generation. Review
the exact diff, local checks, application image and preserving rollout before
calling the new workflow delivered.


## Current implementation checkpoint

The feature branch captures verified completed same-conversation films only for
local inference, freezes material/version/revision/export provenance, and checks
all of it before source-based queue publication. Frozen semantic intent now
selects a source alias and inherits saved options, with explicit word-limit
replacement/removal. Planning can append a parented revision or seed a linked
copy under another brand. The same normal director/whole-production wrapper
produces the result in temporary-account tests; this is not native qualification.

Next, supply the director with actual prior visual-source mappings, so preserving
shots means selecting real Library sources instead of requesting fresh copies.
Keep source and native bounds closed. A revision without an explicitly changed
total duration should fit its proposed edit, not blindly refit the old creation
target; legacy planning keeps its existing behavior. Preserve a complete mix
only when its audio contract and timeline are unchanged, and preserve the
existing presenter in that case. An explicit new voice/score/script must not
reuse incompatible audio. Test Stop, stale source, restart and idempotency at
the whole-controller level before enabling/releasing the workflow. No new native
renderer or speech model is needed.
