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

## Verification and separate runtime finding — 2026-11-12

Local regression coverage: 614 cases passed in the broad 624-case backend run.
Ten assertions expected the previous false-success/clarification or old minimal
event shape; after updating those expectations, both affected modules passed all
38 cases. The 55 relevant native image command/model-selection tests, repository
Ruff checks and Docker build passed. Frontend code is unchanged.

The actual saved-context local-model proposal succeeds on its first attempt.
An ordinary owner-scoped conversation independently inferred two image outcomes,
dispatched Qwen Recompose successfully, retained the original reference for the
second separate action and produced the first real artifact. No decision was
rejected. Pixel inspection, however, found nearly unchanged framing and a heavily
processed texture. The second generation was stopped through ordinary Task Stop;
the first result remains available. This is **not full visual acceptance**.
A same-prompt/reference/checkpoint/resolution/steps/actual-seed comparison at CFG 1
instead of 6 approximately halved sampling time but retained the visual problem.
No global sampling defaults were changed on that evidence.

The configured external sd-cli identifies itself as c92d73c. Upstream later
[corrected Qwen 2.1's flow schedule](https://github.com/leejet/stable-diffusion.cpp/pull/2048).
This is a runtime compatibility lead, not proof that it explains all unchanged
framing. The existing guided image engine is pinned to e239e4b0. Next compare that
engine on the same files/brief before qualifying a native adapter change. Keep the
original external script/binary untouched, respect explicitly configured native
execution settings, and preserve model/owner/reference/Stop contracts. Do not
substitute Krea silently or add person-specific prompting templates to hide it.

### Native configured engine follow-up

`AI_STATION_SD_CLI` currently affects diagnostics but the photo adapter ignores
it; the imported original script chooses its own binary. Honor this existing
native-only operator setting for Generate/Edit/Recompose through the owned import
wrapper. With no override, retain existing argv/profile behavior. A configured
missing/non-executable binary must refuse instead of silently using another
engine. Preserve the selected checkpoint, prompt profile and all source argv.
Expose no new HTTP request field or model-authored executable coordinate. Keep
original script/binary bytes intact and cancellation/recovery in the existing
owned process group. Verify the pinned application-owned SDK identity and native load before preserving
rollout, then qualify its actual CUDA rendering and repeat the normal conversation.

Native follow-up verification: 2801 runner/backend image cases passed, with eight
opt-in/platform skips, plus Ruff, Docker build and preserving Compose preflight.
The configured SDK dispatched a real ordinary image Run on CUDA. Its sampled
steps were approximately 2.6 s versus 11.3 s in the CFG-1 legacy-engine comparison;
this is a specific sampling observation, not a general wall-time benchmark.
The initial standalone SDK probe was stopped when missing private CUDA libraries
caused CPU fallback. The completed private SDK bundles only libraries from the
already pinned image, requires the allocated logical CUDA device and leaves the
host driver and external pipeline untouched.

Rendering quality remains unresolved: the newer engine still produced a near-copy
with processed texture. A VAE tensor-cast probe produced identical pixels and was
reverted; it is not evidence of repaired quality. Diffusion, text encoder and
vision projector hashes match the guided recipe. The configured BF16 VAE is a
different file representation from its original-publisher F32 VAE; that difference
alone does not establish corruption or incompatibility. No model or sampling
preset has been silently substituted.

Next isolate the visual brief contract from model fidelity: preserve only requested
invariants, express requested changes relative to the references, and keep multiple
variants concrete and distinct. Reuse the existing subject-neutral ImageVariation
contract/compiler from agent_image_scenes where useful, rather than fixed person
or camera templates. Then repeat the ordinary two-output conversation and inspect
both actual views. A successfully created image file is not proof that the visual
change succeeded; full visual acceptance and goal completion remain pending.
