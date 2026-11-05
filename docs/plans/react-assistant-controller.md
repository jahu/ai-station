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
current turn's frozen attachments and this controller's verified owned outputs.
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
