# Recurring reference-photo agents

The user's goal is to keep a recognizable character while obtaining distinct
poses, settings and expressions over time. A small-edit operation is a poor
starting point: its legacy identity prefix explicitly preserves pose, camera
angle and composition. The old preparation contract also accepted descriptions
of an already completed image and supplied goal, system guidance and duplicated
prompt/edit fields without a clear hierarchy. It supplied no prior-shot context.

## User flow

In an image agent, **What should this agent create?** is the main instruction.
**Same person, new scenes** selects Recompose with instruction-only prompting,
reviewed references and local-model preparation. **Vary shots between runs**
requests concrete setting, body pose and expression choices. **Small changes to
the original photo** retains ordinary Edit behavior and offers an explicit
**Use new scenes** action when that is the desired outcome.

Additional visual details and advanced agent instructions are optional expandable
sections, marked when saved. A duplicated goal stays synchronized as the user
edits it; independently entered style guidance is retained. Image preparation
receives the goal as primary and optional guidance separately, without duplicated
prompt/edit fields. The planned setting/pose/expression and actual image prompt
are inspectable beside the result.

## Execution and history

The existing Task → workflow Run → media-preparation Run → image Run → artifacts
flow remains authoritative. The local model can only propose bounded text fields;
references, backend, dimensions, resources, seed and other reviewed settings are
unchanged by preparation. The new opt-in `vary_scenes` field is stored in the
existing JSON media scope; false is omitted during serialization to preserve
legacy snapshot identities. No database migration or automatic rewrite of saved
agents is needed.

A new-scene plan has a short description and concrete setting/pose/expression
fields. The final instruction separates recognizable identity from reference
composition; no legacy preserve-pose prefix is appended. Generic choices such as
"a different pose" are rejected. An exact normalized setting/pose/expression
repeat is corrected once; a second invalid/repeated plan fails before image
execution. This is planning validation, not visual face-recognition or an image
similarity classifier.

History scans at most 20 recent successful preparation Runs and supplies at most
three matching completed scenes. Both preparation and image child must belong
to this same owner/agent; the child must reference that preparation, have succeeded
as an image-recomposition Run and use the same frozen reference IDs/hashes.
Failed, canceled, unrelated and unassigned-agent records are excluded. The history
snapshot is retained in Run parameters before inference, with structured scene
choices and a preparation event. Existing file checks, permissions, cancellation,
leases, deadlines and publication validation still apply. No new tool authority,
external provider or image access is granted.

## Verification

Normal tests use neutral examples, temporary databases, a fake local text provider
and the existing fake image executor. Cover repeated-plan correction and refusal,
settings preservation, owner/agent/reference isolation, legacy serialization,
explicit UI mode changes, optional-guidance handling, result visibility and
narrow-screen layout. Do not call fake generated images real inference evidence.
