# Conversation, image and recurring-agent reliability repair

Active owner goal, 2026-11-06. Supersedes the qualification scope of
[the initial controller](react-assistant-controller.md). A single-turn image
transformation and synthetic four-tool chain did not prove the user's complete
multi-turn and recurring-reference workflows.

## Evidence

Private workstation records identify the requested quality baseline precisely:
image Run `f32775b4-2309-4016-8151-7863846daeb9` finished at
2026-11-05 19:42:50 UTC / 20:42:50 Europe/Warsaw. Its engine was Qwen,
832×1216, 30 steps, CFG6, instruction-mode Recompose. Recent automatic conversation
transforms used the default Krea2 profile, 768×1024, 8 steps, CFG1, seed42.
Those are different engines/settings and inputs: exit success cannot establish
quality parity. No private prompts/media are published in this plan.

The failed compound turn's inferred ledger invented four immediate future images
for a recurring request. Its tool instructions included batch counts, timing and
agent creation in the image prompt. Four successful renders still left the actual
request unfinished. Agent creation has no image-result binding argument; its
factory intentionally rejects invented image IDs and defaults to Generate. It
therefore cannot currently fulfill 'use the changed image every 15 minutes'.

A subsequent clarification retained an image artifact alias, but the model asked
for the attachment again. This is not evidence that the file disappeared. Inspect
how prior assistant questions, input/result provenance and follow-up intent reach
the model; separately cover old conversation modes and intervening text turns.

## Required repair

1. Restore actual ReAct action/observation dialogue using a qualified agent adapter,
   not a larger imperative matcher. Evaluate the upstream LlamaIndex ReActAgent
   single-step API against the same local model. The existing durable Run engine
   remains the only dispatcher: tools cannot execute outside its permissions,
   ownership, cancellation, recovery and observation contracts.
2. Separate immediate outputs from future automation definitions. Recurrence is
   configuration, never an invented finite set of images to generate now. Freeze
   explicit cadence and reference semantics; do not substitute defaults on failure.
3. Carry scoped conversation assets and useful assistant/user dialogue across
   clarification and text-only turns. Clearly identify available attachments,
   original references and generated results. Verify hashes, owner/conversation,
   trash state and replacement behavior before each dispatch. Do not interpret a
   follow-up acknowledgement as additional host/network/activation permission.
4. Add a source-bound recurring-media draft contract. The model chooses supplied
   result aliases; the server freezes the actual output/reference and compatible
   image profile. The existing factory validates the definition and preserves
   source provenance. Drafts remain disabled until reviewed; never invent paths,
   resource IDs, credentials or permissions.
5. Separate a single visual brief from workflow instructions. Honor requested
   installed models and explicit parameters; make the actual selected profile
   visible. Preserve compatible settings across transformations and recurring
   drafts. Compare neutral controlled cases with the baseline Qwen profile;
   do not alter drivers, original photo_pipe or unrelated model weights.
6. Review whether recurring variation's redundant prose/structured contract causes
   invalid plans or conflicting prompts. Keep generic subjects and all explicitly
   requested invariants/changes. Do not add person/face/pose-specific defaults.

## Acceptance gates

- Neutral real-model request: modify an attached object, then prepare a new variant
  every 15 minutes using **the resulting image**. Exactly one immediate render,
  one disabled draft, interval900, exact output/reference binding, preserved model
  profile; no rendered batch, guessed future dates or success without that draft.
- Upload → clarification → reply → edit works without re-upload. Also cover an
  intervening text question, original versus latest result, new attachments,
  legacy conversations, deleted/changed/foreign assets and worker restart.
- Model/parameter selection remains inspectable. Neutral old-profile comparison
  and actual generated outputs are inspected for requested changes and consistency;
  synthetic success is not reported as visual-quality evidence.
- Real-model research/image/image/agent chains, ordinary chat, analysis and prompt
  writing retain correct intent; no unsolicited generation or implicit permissions.
- Typed tool failures/corrections, Stop, leases, exactly-once dispatch, source-bound
  draft review and account isolation pass normal fake integration/security tests.
- Backend/Runner checks, applicable frontend gates, migrations, image/Compose and
  reviewed PR to develop pass before safe deployment with a database backup.
- Inspect deployed multi-turn and recurring-reference behavior and retain private
  evidence. Keep the goal active until these checks prove the complete repair.

## Framework evaluation

Upstream provides ReActAgent.take_step and handle_tool_call_results. These allow
one model step at a time, with actual tool observations supplied by the existing
Run engine. Full framework-managed tool execution would duplicate its durable
scheduler and is excluded. No framework Context pickle, credentials or private
reasoning trace becomes user-facing state. Persist canonical validated actions
and observations; rehydrate bounded framework state when a worker resumes.

Primary references:
- https://developers.llamaindex.ai/python/framework/understanding/agent/
- https://developers.llamaindex.ai/python/framework-api-reference/agent/

The concrete adapter/dependency decision requires local-model comparison, not a
framework name alone. All qualification examples are neutral; this work does not
optimize sexual transformations of real people.

## Candidate implementation and evidence (not deployed)

The selected dependency is `llama-index-core==0.14.25`, without the meta-package,
embedding plugins or a new provider. `ReActAgent.take_step` proposes exactly one
operation; an ephemeral text-only bridge delegates inference to the station's
selected provider. Actual persisted action/observation records rebuild each step.
The `llamaindex-react-v1` protocol applies to new turns, while unmarked historical
Runs retain their original JSON protocol. No routing rule matches subject words.

A typed immediate/automation plan prevents future recurrence from becoming a
finite batch of immediate renders. Recurring image definitions use the existing
Agent factory with exact cadence, result snapshots, source lineage and compatible
rendering profile. Non-image definitions retain the existing model-assisted
factory. All definitions remain disabled for user review.

Private neutral real-model probes on the managed Qwen 9B selected Recompose and
then an agent with the actual result alias and 900-second interval, both with
explicit non-thinking and the runtime's default completion settings. Six neutral
interpretation probes passed. These probes used synthetic tool observations and
do not qualify generated media quality or the complete deployed workflow.
New raw-ReAct worker/API tests exercise actual fake image subprocesses and agent
publication across worker/session restarts, rejection/correction of original-
versus-result mistakes, exact cadence, profile inheritance and agent-only requests
without unsolicited renders. Legacy transcript regressions explicitly retain the
old protocol rather than translating fake responses into the new protocol.

Full suite, deployed real workflows, neutral visual comparison and the remaining
acceptance gates above are still required. The goal remains active.

Validation exposed an existing replacement-owner process journal race: managers
for the same canonical registry had separate thread locks and competed for one
atomic-rename temporary file, also risking lost updates. Managers in the single
Runner now share the complete journal transaction lock, including initialization.
The repair does not add a cross-process ownership contract or alter signaling.
A forced-overlap regression and process/deadline/native-runtime tests qualify it;
final Runner-wide checks must pass before deployment.

## Deployed qualification and current-turn follow-up

PR #679 delivered the real ReAct adapter and source-bound drafts to develop.
The reviewed image and frozen native Runner were deployed with an offline SQLite
backup, unchanged records and preserved local/LAN/authentication settings.
A real neutral Qwen 9B conversation produced exactly one Qwen Recompose and a
disabled agent with interval900, bound to that actual output and its 30-step/CFG6
profile. Execution success is separate from visual acceptance: the result changed
the object's color but failed the requested new setting. A controlled same-source,
same-profile English-instruction comparison is pending; quality is not yet qualified.

A different three-turn test retained the original artifact through clarification
and an intervening text answer, but the final agent-only request was incorrectly
interpreted as also requiring an immediate image. That QA root was stopped, and
its unrelated initial chain was allowed to finish. The definition itself retained
the correct original reference and 1800-second cadence.

The planner had serialized the current instruction before older dialogue inside
one JSON message. The follow-up candidate sends read-only metadata first, actual
historical user/assistant messages in order, and the current request last. Validation
feedback stays before the current request; ReAct feedback is metadata rather than
a replacement user command. Earlier requests resolve references but are not an
outstanding work queue. There is no language/keyword matcher or subject-specific
branch. The same managed 9B, with the actual failed history, passed replacement,
continuation, ordinary explanation and modify-then-automate contrasts. Full local
checks and deployed multi-turn qualification remain required for this follow-up.

## Reference content versus the operation's model

The controlled neutral Qwen reference-edit comparisons retained the old setting
with Polish instructions, equivalent English instructions, lower CFG and a full
structured target-scene instruction. These tests do not establish a prompt-language
root cause, and no language rewrite or sampling hotfix is being shipped from them.
The configured alternative editor changed both requested properties, retained the
reference object's shape/hardware and produced a clean new setting on the same
workstation. This is evidence for that neutral case, not a general model benchmark.

New conversation transformations must respect the configured model for their
operation unless the user explicitly chooses another model. An image reference
selects content; it must not silently select its historical generator. Compatible
source settings may be reused when that model is actually selected. A recurring
definition bound to a newly produced result retains that result's compatible model
and settings, unless explicitly overridden, to reproduce the reviewed workflow.
A separate policy coordinate preserves historical queued requests and receipts.
No model weights, external runtime or original photo script is changed.
