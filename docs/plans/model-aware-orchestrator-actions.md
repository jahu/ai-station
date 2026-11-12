# Model-aware tool actions and honest planning recovery

## Report and reproduced cause — 2026-11-12

A clear request for two separate images from one reference ended with a generic
clarification, before any image Run. The independently inferred outcomes were
correct: two image results, both bound to the same supplied alias. An opt-in
proposal-only reproduction with the saved context and actual local model rejected
both attempts: `reference_layout=beside` was proposed for the configured Qwen image
backend. That control is supported only by Krea2 reference operations. It describes
internal reference placement, not two final pictures or a collage.

The global ReAct guidance exposes a backend-specific hint alongside a common
image schema. The framework's ToolMetadata also filters out schema constraints
such as additionalProperties/allOf. Correction passes only a short error string,
without the rejected structured action. Rejections discard their diagnostic from
Run events; exhausted technical failures are incorrectly presented as successful
clarifications. These are contract/recovery/observability problems, not a reason
to specialize routing for people, camera angles, Polish or this particular prompt.

## Implementation

1. Preserve the complete closed tool schema through the existing LlamaIndex
   adapter. Advertise model/mode-specific optional controls and conditions from
   the already frozen image catalog, including the effective default. Keep the
   existing typed dispatch, identity/fingerprint, owner and permission checks.
   Share the control definition with image request binding to avoid schema drift.
   Never silently change the selected model or strip a requested constraint.
2. Remove backend-specific directions from the global controller policy. Tools
   advertise their own applicable parameters. Requested separate outputs require
   separate successful production steps unless the tool explicitly supports a
   batch; internal reference placement never determines output count.
3. Give correction the rejected structured proposal, safe validation diagnostic
   and applicable parameter contract. Keep the original instruction/outcomes and
   reference aliases fixed. Bound retries; never execute invalid proposals or
   persist framework scratchpad reasoning as public activity.
4. Retain bounded private proposal/diagnostic attempts and safe structured rejection
   events. Exhausted planning errors fail honestly while retaining earlier results;
   they must not ask the user to repair an internal tool contract. Preserve the
   valid terminal fallback when all requested outputs are already verified.
5. Keep the existing ask_user tool for genuine missing inputs/ambiguity, including
   separate files versus a composite when the request does not specify it. A
   clear request for two photos needs two generations, not a clarification loop.

No new execution engine, transport, database schema, model download or arbitrary
host access. Existing queued request bindings remain authoritative. No subject
recognition, keyword router, fixed pose list or model substitution.

## Acceptance

- Regression: Qwen default versus explicit Krea2, Krea2 default versus explicit
  Qwen, Generate versus reference modes, source inheritance and unavailable or
  changed catalogs. Unsupported controls stay rejected; model choices stay fixed.
- Actual formatter retains closed/conditional schemas; correction includes the
  rejected action without replacing the user's instruction. Diagnostics survive
  failure and remain owner scoped, bounded and free of public scratchpad text.
- Durable current-ReAct tests produce two separate images from the same reference
  for count=2 and two ordered image outcomes, plus a non-person example. Test a
  genuine clarification/follow-up, Stop, partial-result preservation and no false
  completion after exhausted retries.
- Repeat the saved-context local-model proposal test, then one ordinary real
  conversation through the worker producing two separate actual images. Inspect
  source lineage, counts, completed Runs and the resulting views. Do not claim
  historical raw decisions were retained: the original build omitted them.
- Relevant backend/controller/provider/permission tests and UI checks if changed;
  reviewed PR to develop, preserving deployment while idle, then runtime evidence.
