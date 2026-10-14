# Workstation inspection from the platform assistant

An explicit request such as `Pokaż użycie GPU i RAM` or `Show GPU usage`, or the **Inspect workstation** action, creates an orchestration Run and a durable `system.inspect` child Run. The worker reads the typed Host Runner `/v1/hardware` and bounded `/v1/gpu-processes` endpoints. The HTTP request only enqueues; no LLM, model load, external provider or process control is needed.

The child requires `filesystem_read`, requests no GPU allocation and accepts no path, URL or command. It records tool events plus JSON and Markdown artifacts, and publishes the observed report inline in the conversation. Only numeric sensor fields and bounded names are retained; unsupported measurements remain unavailable. GPU telemetry is a new observation, while runtime status is explicitly labelled as saved metadata with observation timestamps. The report includes bounded NVIDIA compute-process observations; it does not control processes or list graphics-only applications.

The Runner request has an eight-second deadline. Cancellation before/during observation prevents report publication; it never signals a hardware or external runtime process. A vanished worker's unstarted safe claim can recover through the ordinary queue. Uncertain started completion follows the existing inspection policy rather than replaying writes. Report/message/artifact records and successful state publish in one transaction. Existing data-root artifact rules apply.

Selecting this action rejects attachments and mutation scopes. Ordinary explanatory questions such as `What is a GPU?` stay in conversation routing. Ambiguous requests can be routed by the validated planner, whose output cannot change this tool's permissions or input schema.

## Planner follow-up context

At enqueue, up to eight recent messages are copied into immutable Run parameters. Individual excerpts are at most 1,000 characters, and additional history plus the current instruction uses a 4,000-character history budget. Larger current instructions receive no additional history. Partial, superseded and routing-only messages are omitted; only the same conversation is queried. Metadata, attachment IDs and earlier consents are never copied. The current turn still supplies all scopes and references.

This context helps classify follow-up discussion; it does not authorize repeating previous actions, supply pixel vision or create a multi-action plan. The existing chat executor supplies its own bounded conversational context for the resulting answer.
