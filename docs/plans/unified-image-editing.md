# One Edit workspace with verified changes

User decision, 2026-11-12: replace the public Edit/Recompose split with **Edit**.
One or several reference images are inputs; the instruction defines the change.
Keep old URLs, agent definitions, Run parameters and API operations readable.
Those operations are adapter details, not choices an ordinary user must make.

## Execution contract

- Keep Task → Run → Events → Artifacts and the native typed photo executor.
  HTTP only enqueues. A CPU coordinator owns inspect/plan/render/review stages;
  existing local vision/model-loading and native photo Runs do the actual work.
- Freeze original sources, selected image model/identity, explicit controls and
  user instruction before execution. Source geometry is the default; output
  size/aspect and model-specific controls belong in advanced settings. Choose
  engine operations using reference count/capabilities/geometry, never keywords.
- Inspect actual references when preparing relative changes, so "different"
  is grounded in the source rather than a guessed original view. Use structured,
  subject-neutral expected changes and features to preserve. No person/pose list.
- The selected generator stays fixed. The planner cannot change model, references,
  permissions, GPU selection or arbitrary paths/commands. Compile one concrete
  visual instruction, preserving original feature positions and respecting
  explicit requested changes. New Qwen photo Runs use persisted fresh seeds.
- Review the actual candidate and original references against the requested
  changes. Exact unchanged pixels are rejected independently of model opinion.
  Structured local vision verdicts distinguish passed, failed and uncertain;
  successful process exit alone does not establish visual success.
- Allow at most one corrected generation, from the same original references.
  Preserve both attempts, reviews, evidence and lineage. Uncertain/failed final
  review ends honestly with an inspectable failure; never publish it as an
  accepted edit or silently swap models. No unlimited retry loop.
- A verified root points to its accepted child artifact without duplicate file
  ownership. Unaccepted attempts remain inspectable and clearly marked. Chat
  fulfillment and agents must consume the accepted result, not every candidate.
- Reuse private account scopes, bounded owned local vision runtimes, current
  worker leases/claim fences, idempotent child identities, resource admission and
  Task cancellation. No cloud fallback, new service, shell or model download.

## Implementation sequence

1. Add an opt-in verified-edit contract beside legacy ImageRequest behavior.
   Implement the durable coordinator and structured local vision stages. Reuse
   vision runtime selection and bounded provider streaming without creating
   hidden user conversations for workspace operations.
2. Enable new Edit submissions from Images, the assistant and image agents;
   retain old saved operations and technical APIs. Unify public operation labels
   and entry points in Images, Library and agent settings. Support several refs
   and advanced geometry, keeping explicit models and controls authoritative.
3. Extend workflow/result projection to show preparation, generation, checking
   and correction. Only an accepted artifact becomes the final result; rejected
   candidates retain a review label in history/Library.
4. Fake-executor tests cover unchanged candidates, missed changes, uncertain
   reviews, successful correction, the two-attempt bound, cancellation, recovery,
   model/source changes, ownership, and accepted-result selection. Frontend
   tests cover one Edit option, multi-reference editing, old links/settings,
   progress and failed verification without a misleading completed preview.
5. Run relevant Python/runner checks, frontend lint/types/build, Docker/Compose
   validation, full-diff review and PR to develop. Preserve local data during
   deployment. Real local qualification must include an unchanged negative
   control and an ordinary source-relative edit; inspect actual images and
   review records before claiming success.

## Verification record

The implementation keeps legacy API/Run contracts explicit while new controllers
freeze verified editing and expose one editing tool. Pixel comparison is separate
from local visual review; the latter also judges the original request independently
of generated criteria. A format repair may correct JSON once without repeating
image generation. Accepted file ownership, Trash history, account boundaries,
Stop, claim recovery, explicit retry, raw ReAct multi-reference dispatch and agent
final-result delivery have executable fake-provider/native tests.

Local checks include frontend format/lint/types/build, the complete frontend
suite (1,250 tests), Python/Runner lint and formatting, Compose validation and a
successful application image build. A broad relevant Python/Runner selection
passed 4,362 cases with eight explicit opt-in skips; eight initially failing
historical assertions were corrected and their affected modules then passed all
73 cases. The native motion-plan tests run separately (58 passed) because their
random parameter IDs are incompatible with xdist collection. Final changed-code
checks and real local qualification are recorded separately below; no synthetic
verdict is evidence of real image-model accuracy.

Reviewed implementation head `26b8f5a0` additionally passed 800 selected backend
regressions, including the complete new workflow, current raw ReAct with one/two
references, agent final-result delivery, account input isolation, recovery/retry
and native image contracts. The preserved local deployment now runs that head.
Real local qualification rejected three negative controls: identical decoded
pixels, a different PNG retaining the old room rather than the requested garden,
and a clean near-frontal image supplied for an explicit side-profile request.
The latter two verdicts came from the installed local vision model reading the
actual source/candidate images, not from a fake provider or filename comparison.
The ordinary Qwen edit completed successfully with the actual selected model:
the indoor room became a leafy garden while the subject, clothes and identifying
mark stayed consistent. The accepted output was inspected locally; a model verdict
is not a general guarantee of perfect visual perception. The qualification also
exposed incidental original properties copied into the proposed preservation
list. Generic planning guidance now distinguishes source observations from
user-required invariants and requires all final-plan fields to agree. Private inputs/evidence remain
outside Git and are not public website/README assets.


The real plan-only follow-up exposed a generated layout hint on Qwen, which has
no such control. The closed plan schema now advertises null for that optional
hint; if emitted anyway, its omission is audited before rendering, preserving
the selected model and visual brief. Explicit user controls retain normal API
validation. Proposed preservation checks also cannot create new user obligations:
review may mark an incidental, unrequested preservation check `not_required`,
with evidence. It cannot waive a change criterion, and independent verification
of the original request must still pass. Follow-up tests cover both boundaries,
including a false-goal verdict despite dispensable preservation criteria.

## Multi-reference Krea correction — 2026-11-13

Diagnosis of an actual two-reference edit found that the native adapter always
aligned the first reference, even when the frozen request selected `beside`.
The upstream patch API assigns separate placement arguments to the first and
last reference; our public control describes the whole operation. Treating the
first arbitrary image as a layout-preserving scene silently contradicted that
contract. Both references must receive the selected placement. No subject-type,
pose-word or person/scene heuristic may assign a reference role.

Krea also replaced an omitted seed with 42 before enqueueing, and conversation
profiles inherited source seeds. Preserve explicit seeds, but freeze fresh image
seeds for omitted selections across both native image backends. A bounded edit
correction with an automatic seed must use a persisted different seed; transport
retries of that photo Run retain it. Voice seed continuity is unrelated.
Both initial and corrective automatic draws exclude reference noise, including
legacy native receipts, and retain unsigned 32-bit wraparound semantics.

Qualification requires native argument coverage with one/two distinct reference
sentinels, automatic/explicit seed and correction regressions, and an actual
two-reference Krea edit through the normal worker with independent image review.
Retain selected checkpoints, source order, account isolation and the two-attempt
limit. Failed or uncertain review must still prevent accepted-result publication.

The controlled native comparison kept the same checkpoint, prompt, seed and
references. Removing the hidden layout pin changed the previously seated result
to standing, but the frame still excluded part of the requested subject. The
existing goal-conditioned reviewer falsely described the cropped result as
complete. Its image inputs also lacked per-image role labels.

Add an independent candidate-only observation before review, without the user
goal or criteria. Persist visible extent, clipped content and uncertainty as
ordinary local vision evidence. Label every actual review image as an original
reference (with its index) or the candidate. A partially met criterion fails;
unresolved disagreement with the independent observation is uncertain.

For Krea's single bounded correction, failed changes with passed preservation
checks may lower automatic reference amplification to the neutral 1.0 and
grounding resolution to at most 512, within the installed adapter's supported
range. This relaxes image copying without keyword/subject heuristics. Do not
relax after a failed/uncertain preservation check, or override an explicit
operator value. Conversation preset values are distinct from operator tuning.
Keep the selected checkpoint, sources, output size and the two-photo limit.

The real cropped negative control also showed that correct independent
observations alone do not prevent an optimistic visual verdict. Before accepting
a passed review, run a separate text consistency audit over the observation,
original goal, criteria and proposed verdict. Contradiction vetoes acceptance
and supplies bounded correction feedback; unresolved uncertainty vetoes success.
Do not turn an omitted incidental detail into a new preservation requirement.
Plan atomic change criteria so meeting one part cannot satisfy a conjunction.
These are ordinary local reasoning children, with the same scope, leases,
cancellation and recovery; they add no photo attempts or execution permissions.

The complete Krea qualification still failed the requested framing after both
bounded attempts, and both results were correctly rejected. Therefore fixing the
adapter and verifier alone does not establish task fitness. New conversation
controllers freeze `model-fit-v3`: their captured installed-model catalog
describes instruction-native versus reference-conditioned editing. For automatic
edits, the planner selects a model suited to the requested structural/extent
changes; the configured default is a preference, not a capability guarantee.
Explicit user model choices stay authoritative, and the selected checkpoint
remains fixed during the edit. Older frozen controller policies retain their
prior default/source behavior. This uses semantic planning over finite adapter
capabilities, not subject-specific wording rules or silent post-failure swaps.
