# Structural image edits (NR-03)

Keep the existing photo executor and installed runtimes. Explicit model choices
remain authoritative. Offer **Auto · match this edit** for Edit/Recompose; its
selection is saved with the workspace, not substituted into global defaults.

A bounded, deterministic read-only preview identifies active pose/orientation or
object-removal instructions in English/Polish. Quoted examples and negated changes
do not grant a structural operation. Structural edits and reference counts beyond
the configured default's capacity recommend Qwen; other edits use that account's
configured default. No LLM, source-image inspection or generation runs in preview.

The typed request opts into Auto without an explicit model/backend or backend-only
controls. The controller resolves it once before enqueue, applies the selected
model's existing presets, and freezes the actual model and selection reason on the
ordinary Run. UI preview binds the personal-default revision so a concurrent change
cannot mix another model with old form presets. Retry retains the exact selected
model; a new variation may ask Auto again. Existing request identities remain
unchanged when Auto is absent. No schema/native API change is needed.

Auto uses the existing instruction-only edit profile, avoiding a legacy identity
template that can contradict pose/object changes. Explicit models retain the
classic-profile option. Backend-specific seed/reference controls remain explicit
model settings; Auto retains common dimensions/quality controls and real presets.

Show the actual previewed model and why it was chosen. For an explicit LUSTIFY
selection, show a structural-edit recommendation with an action to choose Auto;
never silently replace the selection. Backend-specific controls are available with
explicit selection; shared output/quality settings remain available in Auto.

Qualification uses fake API/worker tests for routing, explicit overrides, frozen
retry, revision races, source ordering, ownership and original request identities.
Compiled desktop/mobile checks cover actual selection and saved variations. Real
neutral same-source object-removal and pose fixtures compare model-appropriate
presets and record whether the requested change occurred. A finished Run alone
is not visual acceptance. Existing scripts/models and private media stay untouched.

## Recorded qualification, 2026-10-30

One neutral 768×1024 source shows a fictional, fully clothed adult standing beside
an empty bench and holding a red book. Each operation uses the same source and
instruction, with existing model-appropriate presets: Qwen Image 2.1 at 30 steps;
LUSTIFY Turbo Q4_0 at 8 steps with aligned references/strength 4.

| Requested change | Observed Qwen result | Observed LUSTIFY result |
| --- | --- | --- |
| Remove book and lower empty hand | Book removed; empty hand lowered; identity, clothing and scene retained. | Book removed, but hand remains raised with unclear/fused fingers; texture changes more strongly. |
| Sit on the bench, retain book | Subject seated on original bench with feet on ground and book retained. | Subject remains standing; requested pose is not performed. |

These are actual generated outputs inspected visually, not conclusions from Run
status. They qualify the Qwen recommendation for these fixtures, not every
possible instruction or LUSTIFY preset. No private images are published in Git.

The 280-case complete affected-family baseline passes. Final serialization changes
have 104 passing complete-family cases, followed by 44 model/routing/private cases
after preserving custom Qwen selection. The UI's 953-case baseline and final
31-case Images/workspace families pass, along with types/lint/format/build. Saved
Auto intent round-trips without injecting provisional backend/default controls.
Compiled desktop/mobile acceptance and final rollout are recorded separately in
`data/acceptance/image-structural-edits-20261030/`.
