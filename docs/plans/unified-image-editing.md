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
