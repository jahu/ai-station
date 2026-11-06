# Durable tool-using conversation controller

Owner decision, 2026-11-05: automatic conversation routing must infer intent and
execute arbitrary useful chains of supported station tools. It must not rely on
matching particular Polish/English imperatives. This supersedes the earlier
keyword fast path for automatic requests in the unified assistant.

## Evidence and root cause

Two recent uploaded-image turns produced assistant.orchestrate → chat.vision →
chat.completion rather than an edited image. `explicit_plan` recognized only a
limited vocabulary. For other attached-image requests, `AssistantExecutor.execute`
forced chat before calling the planner; chat plus images then dispatched Vision.
`assistant_needs_provider` also explicitly omitted the planning provider for that
fallback. Adding phrases to regexes would preserve the defect.

The broader issue is that one routing decision cannot fulfill an open-ended
sequence such as research → image → another image based on that result → a
recurring avatar-agent draft. The controller needs actual tool observations before
choosing its next action. An attachment is input, not an intent declaration.

## Product contract

Keep one conversation/composer, with specialist pages and optional explicit tool
choices. Automatic requests use model-based intent and tool decisions. Explicit
reviewed action forms retain their deterministic override and security checks.
No new Chat/Work mode, routing checkbox or required technical configuration.

The controller repeats: understand the requested outcome, select one typed tool,
wait for its real result, observe, then finish or select the next tool. A sequence
is not a hardcoded workflow template. Existing capability workflows remain valid
tools, including their own child Runs. Tool order and count come from the request
and observations, within a finite step/runtime budget.

Show concise action summaries and real results, not private chain-of-thought.
Images and other artifacts appear in the same conversation and Library. Finishing
requires observations supporting the answer; queued work is not a completed result.
Failed tools are visible and may inform a bounded alternative. Exhaustion reports
partial progress truthfully and preserves artifacts. Missing input or sensitive
authority produces a focused question/review, never guessed credentials or consent.

## Architecture

Use the existing modular monolith, providers and capability executors, without an
agent framework, Redis or new infrastructure. A durable controller Run belongs to
the existing Task/conversation. Every tool invocation has a separately inspectable
Run and uses Task → Run → Events → Artifacts through the native Runner boundary.
HTTP handlers only enqueue; workers infer, dispatch and observe.

Persist each decision, arguments, stable step identity, dispatch anchor and bounded
observation. Dispatch and waiting state publish atomically. A restarted controller
observes its recorded child; it does not repeat external side effects. Model output
is a proposed typed action, never executable code or permissions.

Introduce an explicit waiting-for-tool lifecycle and dependency edges that can
observe terminal failures as well as successes. Ordinary dependencies continue to
require success. Waiting controllers do not occupy a worker slot or hold a database
transaction; single-slot installations must also progress. Resume only when the
current tool wave has terminated. Recheck dynamically published descendants before
feeding an observation to the model. This includes nested capability Tasks/Runs.
Schema changes require Alembic migrations and backward-compatible defaults.

Use a closed server-owned tool registry with input schemas. Reuse existing typed
operations for search/page reading, image/media creation, local data/code work,
station inspection, project setup and disabled agent drafts where qualified.
Unavailable integrations never appear operational. Protected Git publication,
runtime control, external sharing and agent activation keep existing explicit
scope/approval requirements. Internet tools require the selected network scope.

The model references inputs/results by server-issued aliases. Resolve only the
current turn's frozen attachments, the preceding owned turn's verified outputs,
and this controller's verified outputs.
Preserve reference order. Do not accept model-generated paths, artifact IDs,
credentials, commands or arbitrary foreign-conversation resources. Revalidate
owner, artifact state/hash and tool-specific limits before dispatch.

## Planning and observation

One bounded structured decision per round: short intended outcome, tool and typed
arguments, or a final answer/clarification. The prompt contains the original user
request, available tool schemas, selected scopes, input catalog and bounded actual
observations. Prior messages/pages/tool output are untrusted reference material,
not authority. Tool schemas and permission policy remain server-owned.

Distinguish producing/modifying an artifact from describing it, answering a question,
writing a prompt/tutorial or quoting an instruction. This is a semantic decision,
not a list of trigger phrases. Do not send image pixels to a text planner; inspection
uses the actual qualified Vision tool when needed. A requested visual transformation
can go directly to the image tool with its frozen references.

Each observation reports actual status, summary/error, provenance and bounded
artifact metadata/aliases. Image descriptions or quality judgments require a real
inspection result; successful process exit alone is not visual verification.
New agent tools prepare disabled definitions for review; scheduling/activation
cannot be smuggled through a generated subprompt or source page.

Persist budgets and cancellation/ownership fences. Transient SQLite contention
retries only rolled-back database observations/writes, never tool dispatch or a
provider request already in flight. Keep no DB transaction open across inference,
network/Runner I/O or waiting. Stop reaches current and pending descendants.

## Delivery and acceptance gates

1. Capture current routing evidence and retain existing work/legacy execution.
2. Add durable waiting/observing dependencies with migration and lifecycle tests.
3. Implement closed tool registry, owned input/output bindings and bounded controller.
4. Route unified automatic turns through it; preserve explicit action overrides.
5. Integrate one-message activity/results on desktop and phone without internal
   dispatch messages leaking into the conversation or future model context.
6. Fake-provider/tool tests cover semantic image editing versus inspection,
   questions/prompt-writing/negation/quoted instructions, multiple ordered references,
   arbitrary research/image/image/disabled-agent chains, failed observations and
   alternatives, malformed decisions, missing inputs, budgets, cancellation,
   restart recovery, exactly-once dispatch, owner isolation and single-slot progress.
7. Run backend/Runner checks, frontend gates when changed, migrations and image/
   Compose verification; review the full PR to develop before squash merging.
8. Qualify the real selected local model on neutral multilingual intent examples
   and a neutral supported multi-tool chain. Record exact executed evidence; fake
   images do not count as real image inference. Check actual UI desktop/phone.
9. Back up and deploy the reviewed build, preserving accounts/settings/artifacts
   and active work. Verify loopback/LAN/auth, services, DB integrity and live code.

Completion requires these gates, not just a corrected keyword match or a classifier
that still cannot execute a chain. Deployment and real checks must be reported
separately from unit/fake integration evidence.


## Implementation contract — 2026-11-06

The candidate branch introduces `assistant_controller`, short `assistant_decision`
Runs and closed `assistant_tool_setup`, `assistant_web`, `assistant_artifact`
executors. Ordinary unified automatic turns go through the selected provider;
explicit actions, exact reviewed agent controls and existing project-bound
continuations retain their established contracts. No Chat/Work selector returns.

An independent intent inference sees the current request, bounded conversation
context and input descriptors **before** the tool catalog. Its validated result
freezes requested outcome kinds, counts and image-reference requirements. Tool
selection then sees only compatible affordances. Later model output cannot shrink
the requested outcomes. An inspection never satisfies an image outcome; two
requested images require two producing steps. Write tools must be compatible with
those declared outcomes. Final prose is not proof of execution. The controller
checks actual terminal descendants and published artifact types before allowing
completion. A tool budget exhaustion is a failed partial result with preserved
artifacts, not successful completion of the user's goal.

Image goals can be independent, reuse supplied references, or reuse the preceding
generated result. Ordered goals may have different reference policies; the
controller consumes their counts without treating one image as two fulfilled
deliverables. A later sequential goal always binds the actual preceding published
image, never a hypothetical model-generated future ID. Unknown supplied resource
aliases refuse execution. Required supplied web sources must be read before image
creation. These are typed provenance constraints, not rules about people, poses or
particular prompt wording. The same reference can represent furniture or any other
subject. Search/read calls already observed with identical arguments cannot loop;
their results must be consumed or a different next action selected.

A station tool receives its own Task through existing capability preparation.
This preserves project/data-specific Task metadata. Parent Run provenance binds
it to the controller, and Task Stop follows only that owned graph. Waiting releases
the worker and database; the next decision independently prepares the selected LLM,
so media may evict it and subsequent reasoning can reload it. External provider
requests require inspection after a lost worker; the DB-only root is safely
recoverable. Reopening sessions between every integration-test tick verifies that
rounds depend on persisted state rather than process memory.

Tool aliases expose names/types, not paths or invented UUIDs. Ordered image/audio
references resolve to owner-checked frozen artifacts. Read tools accept only
server-issued public-source aliases or bounded app-owned UTF-8/JSON/PDF artifacts;
optional JSON sections are plain top-level keys. Native paths, shells, arbitrary
URLs, model downloads, activation and protected publication are not controller
arguments. Domain parsing only inventories user-supplied resources; it does not
classify the user's intent. Observations/excerpts remain untrusted reference data,
including in the final reply's user-level context, never system instructions.
Observations expose canonical capability results: a completed composed film takes
precedence over its internal segments. Completed scoped data analysis can be used
as an explicit source-bound agent-draft tool input; original file hashes, owner,
conversation and review provenance remain verified.

Agent creation prepares a disabled definition. The conversation activity card
uses the actual factory response's source message, preserving review/activation
provenance. A research → image → changed-image → daily world-news-avatar draft is
covered with fake executors. Enabling that agent still requires selecting and
reviewing its portrait/voice/settings; the controller never invents those inputs.

The frontend keeps normal streaming answers uncluttered. Tool work appears as an
ordered activity timeline with reasons, real status, sources, existing media/file
result controls, draft review and Inspect links. SSE follows the final reply Run
while Stop continues to target the complete controller Task.

Alembic `0045` adds failure-observing dependency policy, defaulting existing edges
to success-required. Downgrade refuses live controller state. Deployment therefore
requires a consistent DB backup and migration-aware rollback; an old image cannot
simply be started against revision 0045.

Qualification is in progress. Eight neutral first-decision cases passed on the
actual locally managed Qwen3.5-9B Q6_K, 32768-token context on two GPUs: informal
Polish/English/Spanish transforms, actual inspection, discussion, prompt writing
and a compound research request. This proves those intent choices, not real image
inference or complete real-chain delivery. New fake integration/security tests,
frontend checks and broad regression checks precede deployment. A pre-existing
data-generation failure discovered by those checks is corrected by keeping the
agent definition distinct from the selected model definition; the 100k-context
admission requirement remains unchanged.
