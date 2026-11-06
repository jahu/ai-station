# Generic recurring image variations

## Intent and correction

An image agent must work with products, rooms, buildings, illustrations, people
and other subjects. The first reference-photo implementation overfit to people:
it required setting/pose/expression and injected a same-person photograph prefix.
Examples also encouraged particular expressions. That can add unrequested changes
and excessive detail. User feedback on unnatural details prompted this correction.
One saved plan also contained contradictory visibility/orientation directions;
that is evidence of a planning issue, not proof of a particular model defect.

The generic planner now takes one authoritative user brief and optional secondary
guidance. It determines only the aspects relevant to that brief. It returns:

- `description`: one complete image-generation prompt, up to 1800 characters.
- `preserve`: up to six invariants explicitly requested by the user.
- `changes`: one to four named aspects with concrete visual directions.

No aspect is intrinsically a pose, facial expression, location or human attribute.
References may have different subjects/roles. The text planner must not invent
unobserved reference attributes. Its description includes all requested invariants
and changes. The compiler builds one executable prompt containing the description,
every requested invariant and every concrete change, without subject, photography,
anatomy or quality-booster prefixes. Explicitly changed properties must differ from
the references; preserving one feature cannot freeze other attributes requested to
vary. The planner must cover every aspect requested by the brief and must not add
unrequested invariants. This prevents planned changes from being silently omitted
from the actual image prompt; it is not a guarantee that a model obeys every direction.

Preparation instructions ask for a small number of appropriate changes and a
self-check of physical plausibility and consistency across position, orientation,
visibility, scale and materials. This is a prompt-writing instruction, not an
implemented visual judge or a certificate of generated-pixel quality. Increasing
steps, changing CFG or adding face/teeth keywords is not a generic solution.
Runtime/model settings and existing model-specific recipes are unchanged.

## UI and compatibility

**New variations from references** and **Vary results between runs** replace the
person-oriented labels. The main instruction explains what stays and changes;
additional visual/system guidance remains optional and expandable. Results display
the plan, requested invariants, actual prompt and recorded generation settings
when available. That separates intent/planning from the backend/steps/CFG used.

The existing `vary_scenes` JSON policy and reviewed references/settings are retained.
False is omitted from serialization to preserve legacy scope identities. Old
setting/pose/expression plans and frozen histories remain readable through a
read-only adapter; stored records/artifacts are not rewritten. New plans use the
generic contract. There is no database migration or automatic agent-definition edit.

## Execution boundaries

The existing Task → workflow Run → media-preparation Run → image Run → artifacts
flow remains authoritative. Models can propose bounded text only; they cannot
change backend, dimensions, references, resources, seed, permissions or execution.

History scans at most 20 recent successful preparations and supplies at most three
plans whose image children completed successfully for this same owner/agent and
frozen reference IDs/hashes. Historical plans are context, not observations of
pixels, requirements or authority. Both an identical normalized final prompt and
an identical normalized change map trigger one correction attempt; a second
invalid/repeated plan fails before image execution. Differently cased duplicate
aspect keys also fail. This is bounded planning validation, not semantic image
similarity detection. Cancellation, deadlines, file checks, leases and publication
validation retain their existing contracts.

### Duplicate-plan recovery

The 2026-11-05 failed preparation returned exactly the last completed description
and change map twice, including after correction. Full historical prompts had been
supplied in the requested output shape; correction then echoed the rejected JSON as an
assistant message. The initial instructions did not explicitly require a different
concrete direction from every completed plan. This left a strong copying anchor
and an ineffective generic correction request.

Keep complete history in Run parameters for audit and duplicate validation, but
give the model only bounded earlier change maps and their Run IDs as exclusions.
State novelty explicitly within the user's brief. On a duplicate, retain the
original reviewed request and append structured feedback identifying the rejected
changes and asking for a new concrete direction plus a consistent final prompt.
Do not echo the rejected prompt as another assistant example. There are still
only two attempts, within the existing deadline/cancellation contract. A second
duplicate fails before generation; repeated images are not accepted as a fallback.
Tests replay the duplicate → fresh-plan sequence, verify correction context and
the complete audit snapshot, and retain duplicate → duplicate refusal coverage.

### Database contention during streaming

A subsequent preparation failed after streaming 158 deltas because SQLite's
`BEGIN IMMEDIATE` could not acquire a writer slot within its busy timeout. WAL
was already enabled. Treating transient contention as a terminal executor error
discarded the in-flight preparation; increasing the global timeout or redispatching
the model is not the remedy.

The media stream now retries only rolled-back database observations/event writes
within its existing execution deadline, retaining the same provider stream and
pending token. Each attempt rechecks the durable worker/claim and terminal/cancel
state. Lost ownership stops observation, cancellation closes the stream, and
non-busy errors propagate. No model call, native dispatch, generation or other
external side effect is retried. Complete Run history remains unchanged. Tests
hold a real temporary SQLite writer lock across both token arrival and cancellation
polling, then verify a single provider request and ordered, exactly-once deltas.

## Validation and further diagnosis

Use temporary databases, the fake local provider/photo executor, and neutral
wardrobe, building, illustration and portrait cases. Verify no injected subject
or medium, preserved settings, owner/reference isolation, duplicate rejection,
legacy-history compatibility, editor behavior and mobile layout.

To attribute a visual defect, keep a neutral reference and concise prompt fixed
and vary one factor at a time: planning output, a model-supported sampling setting,
or the model itself. Record the exact prompt/settings and compare the results.
Do not call fake workflow tests real image-quality evidence or change global
sampling presets without a qualified, model-specific comparison. A future visual
review capability would need its own explicit permissions, executor and evidence.
