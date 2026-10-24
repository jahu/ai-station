# Run the clicked agent from its conversation

The inline Run now button currently calls the standalone Agents API. It launches
work but records no conversation-bound execution, so the next question cannot
reuse that result. Route conversation buttons through the existing queued agent
controller; retain the ordinary endpoint outside conversation cards.

A typed request binds the exact creation message/agent, reviewed definition
revision, conversation settings revision and durable client request ID. Reuse
ChatTurnRequest for idempotency with a distinct request hash domain; no schema or
legacy MessageBody/turn hash change. HTTP only queues the ordinary controller.
The worker rechecks exact clicked provenance/revision before normal launch_agent;
review/enable, approval, consent, Stop, source checks and recovery stay unchanged.

An older card must target its own agent. Later natural “this agent” controls should
refer to the latest valid agent operation/creation reference, while retaining the
original verified creation source. Invalid references fail closed. Named target
labels make the button action clear. Keep unsent text, selected tools and saved
Chat mode intact; the explicit button action is an inspectable Work turn.

Conversation cards carry context only when rendered inside that conversation.
Use an independent durable request namespace so retries cannot duplicate work or
consume the composer's pending request. Archived/busy conversation buttons stay
disabled. Standalone Agents Run now stays unchanged. Controller receipts cannot
be regenerated as an ordinary model reply; a new run requires a new explicit act.

Verify exact older-card binding, follow-up target selection, receipt replay and
cross-endpoint conflicts, definition/source/version/permission changes, disabled
and approval behavior, no inference at HTTP enqueue, ordinary report follow-up,
unsent draft/mode preservation, actual compiled desktop/mobile buttons and reload.

A stale Stop of the controller Task must also stop the exact background execution
it just published. Forward only across the verified two-way controller ownership
link for a newly queued workflow, never from an already-running/busy receipt.
Finished workflows are left intact; shared model startup retention keeps its
existing policy. No broad process signals or new execution mechanism.

Creation identity uses the actual successful factory child or creation event plus
its owned parent/conversation and manage_agents grant. An optional planner
annotation is not required for otherwise intact older creation records.
