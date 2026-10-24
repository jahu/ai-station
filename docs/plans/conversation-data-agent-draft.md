# Turn a completed conversation analysis into a persistent agent

The live #412 release supports document-backed analysis in Chat/Work. The next
useful conversation-first increment is an explicitly requested persistent agent
that repeats that analysis, retaining the reviewed inputs and public source scope.
Use the existing agent-draft Task/Run and disabled-definition review; do not add
another agent execution engine or enable an agent automatically.

Resolve an explicit current instruction such as “create an agent that repeats this
analysis every morning” against a completed, visible, same-conversation data result.
Do not infer this from quotes, unrelated instructions, failed/partial results or
another conversation. Existing source_reference/root_binding/validate_workflow and
captured-input verification are the starting points. Freeze the originating user,
result Run and source scope/hash/provenance on the draft preparation Run. Recheck
before saving; changed or missing sources require review. No arbitrary artifact IDs
or model-selected files/URLs can extend the scope.

Retain the original reviewed local data model, data files/documents and public
research settings. New executions should gather the retained live public sources;
immutable captured data is a distinct choice, never silently substituted for live
research. Source availability/activation checks remain visible. Allocate the agent's
own workspace through the existing factory rather than attaching the conversation's
private analysis project. Do not inherit external AI, email, unrelated projects,
extra tools, skills or permissions. The draft stays disabled.

Local inference can draft identity, instructions and schedule, but the controller
retains the exact reviewed source/tool selection. Reuse agent_drafts.enqueue_for_task
and the existing executor with an optional provenance-bound context; optional
fields must remain omitted for legacy request identities. Preserve idempotency,
shared deadlines, Stop and recovery. A result action may provide the same explicit
request if useful; natural conversation and direct UI must share one service.

Inspect actual agent_drafts.Proposal/definition validation and the assistant's
agent.create branch before implementation. Existing factory URL/tool restrictions
must not be bypassed by copying untrusted model output. Test current-message intent,
same-conversation completed ownership, snapshot tamper, paused/missing inputs,
source/permission containment, schedules, Stop, replay, no duplicate Agent and
unchanged legacy drafts. Exercise the compiled Chat/Work review on desktop/mobile;
separate injected drafting from actual local-model or scheduler qualification.

Worktree `.tools/conversation-data-agent-draft`, branch
`feat/conversation-data-agent-draft`, base `ed6cab6` (#412). The implementation reuses the existing agent_draft child, shared settings mapper,
current-message/source/result verification and a restricted identity/schedule schema.
Qualification at source `45338a6`: all 3424 normal Python/Runner cases were
collected (3415 passed, nine explicit opt-in skips); frontend formatting, lint,
typecheck, 752 tests and production build passed. The exact Docker backend and
compiled assets match, and normal/development/private-LAN Compose validate.
Compiled 1440/390-pixel browser cases performed four actual native offline Python
jobs: original document/public analysis, natural Work draft, explicit UI review and
enable, then a committed scheduler tick at a forced due instant. Each agent used
its own workspace and re-read the retained public source. Inference, model catalog
and public responses were injected; this is not new local-model/GPU qualification
or a five-minute wall-clock test. Stop, source/result/permission tamper, restricted
proposal correction, receipt replay and legacy drafts passed the normal suite.
Evidence: `data/acceptance/conversation-data-agent-draft-20261024`. Publication is
PR #413 to develop; merge and rollout must be checked against the authority below.
Use `post-deployment-qualified.json` to establish actual live acceptance. #412 is fully qualified under
`data/acceptance/conversation-document-context-20261024/post-deployment-qualified.json`:
3391 normal Python/Runner passes, nine opt-in skips, 749 UI tests, exact image/assets,
and eight actual native offline Python jobs across first/ongoing Chat/Work and
1440/390 layouts; inference/catalog were injected, no GPU work. Live authority:
`data/acceptance/safety-redeploy-20261012/deployment.json`. Preserve root Memory WIP.
