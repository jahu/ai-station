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

Supply actual completed visual-source IDs and their previous scene mapping to the
director. For an ordinary edit it must choose those Library sources or explicitly
share them across scenes, rather than generate copies from similar prose. The
semantic intent permits new imagery only when the user requests it. Verify the
original render's source descriptors, canonical owned paths and clip windows.
The exported composite MP4 is not a substitute for its original shots.

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

The implementation now supplies actual prior visual-source mappings. A revision
without an explicitly changed total duration keeps its proposed frame counts;
legacy planning still fits the original requested total. The ordinary caption or
identity edit preserves the audio contract, including words, expression hints,
scene timings and score direction. Requested audio changes are explicit semantic
intent; they cannot silently reuse incompatible audio. Whole-production requests
can name a completed owned export as the source of a complete mix/presenter,
with exact contract, hashes, timing and source checks. This optional field is
excluded from older request receipts when absent. Existing strict same-version
retry behavior remains intact.

A generated presenter can carry forward its portrait settings for changed speech;
an unchanged mix/timeline reuses the completed presenter clips. A manually supplied
presenter without a generation portrait requires a new selected portrait when
its speech changes. Never silently remove the presenter or reuse wrong lip-sync.
Stale source authority is a terminal observation for that outcome in the current
turn, preventing paraphrased whole-workflow retries. Stop never adopts/cancels old
source Tasks. New result cards carry their actual revision ID; historical cards
keep the legacy link fallback.

Qualification completed on the reviewed implementation and alias-correction
commits: 482 Studio/assistant regression tests, followed by 38 relevant tests for
the alias correction; global Python lint/format; frontend lint/typecheck,
42 action-result tests and production build; production/development Compose;
the final application image and offline ephemeral migration/API/accounts/compiled
UI probes. The unscoped whole-repository suite was interrupted, not passed;
these successful relevant checks are the documented local equivalent.

Actual ordinary local-model conversation turns delivered a 16-second parented
headline edit and a separately branded widescreen copy. Full MP4 decoding,
480-frame duration, identical actual sources/trims/score, preserved original
history and sampled scene/transition review passed for both. The copy used the
other project's saved palette/type and a new material. The preserving preview
rollout retained data, schema, settings, socket, ports and search, with a SQLite
backup. No renderer, speech model or database schema change was needed.

The first real-model follow-up correctly selected the captured source but also
repeated that same alias in `source_inputs`. Both semantic attempts were rejected
as an unknown media alias; no Studio tool or inference job was dispatched. The
interpreter now removes only a duplicate equal to the independently validated
`studio.source_material`. Other material aliases and unknown media remain invalid.
This is exact typed-alias normalization, not inferred authorization or a fallback
that changes the requested film. Retain the failed observation and test a fresh
ordinary turn after deploying the correction.
