# Platform assistant

The default AI Station screen is a conversation that operates the workstation. The existing workspaces remain direct entry points and detailed inspectors. Ordinary questions, image references, coding requests, agent definitions and media results belong in the same persistent conversation.

## Execution contract

A submitted turn creates a Task and an orchestration Run. The worker selects a typed action from the operational capability registry. Explicit intent takes a deterministic route; ambiguous requests can use a local model to produce a strictly validated plan. A model proposes actions, never grants permissions, selects arbitrary host paths or supplies shell commands. The user can override routing.

An action uses the same domain service as its dedicated workspace. Child Runs inherit Task/conversation provenance and reference their orchestration parent. Image generation, worktree preparation, coding, validation and model loading remain separate inspectable Runs. A planning Run completes when it atomically publishes its child Run; it does not wait while occupying the sole worker. The conversation projects the complete Task tree, errors, validation and artifacts, rather than equating successful planning with successful execution.

Dispatch and its event/message links commit in one short database transaction. Interruption before that commit publishes no action; interruption afterward leaves the durable queued child. Recovery does not blindly replay externally dispatched operations. Cancellation before dispatch prevents child creation; afterward Stop targets the currently active child. Future parallel plans require persisted step dependencies and task-wide cancellation before being enabled.

## Inputs, authority and results

Images reuse bounded decoded uploads and Artifact IDs. Reference order is preserved. Two references (person, clothing) plus an edit instruction route to Qwen Recompose; a single edit source routes to Edit. Outputs appear inline and remain in Library. Text attachments keep existing bounded context and provenance. Vision analysis is distinct from image modification and requires a capable model.

Agent requests create persistent, disabled definitions with inspectable tools, model and schedule; activation remains an explicit action. Coding requires a registered project, versioned trusted configuration and an explicit external-provider grant when applicable. The assistant must not turn a request to discuss code into permission to transmit repository contents. Selected files and data-sharing scope remain visible. Work happens in owned worktrees with validation and review.

No generated completion may claim a tool succeeded without the corresponding Run/result. Ambiguous or incomplete actions ask for the missing inputs. Model-produced URLs, documents, repository instructions and tool outputs are reference data, not additional authority.

## Model and resource orchestration

Chat model selection combines healthy provider models with discovered local files, distinguishing ready, loading and stored models. A stored GGUF is not falsely advertised as a running endpoint. Choosing it creates a typed owned runtime operation. The Host Runner validates the configured model root and executable, records process identity, binds privately and exposes inference through its existing private bridge. It never stops or reconfigures discovered external Ollama/ComfyUI instances.

Runtime instances reserve discovered GPU resources, support explicit unload and recover their owned process identity. Capability planning can request a compatible model/preset; the resource scheduler serializes competing heavy jobs. External models require an explicit provider/data-sharing selection and secret references. Multi-GPU settings follow actual device discovery and model requirements.

## Media and tool growth

Video, avatar, speech and music use the same action/result contracts. Integrate the installed ComfyUI, EchoMimic and speech environments through validated adapters, preserving their original code and models. Each adapter needs real input/output schemas, process ownership, cancellation, recovery and artifact lineage before being advertised to the planner.

## Acceptance scenarios

1. Upload person and clothing references, request a clothing change, inspect the selected operation and ordinary image Run, receive its actual image inline after completion.
2. Ask an ordinary follow-up and receive a streamed response with persisted context.
3. Request a recurring agent, inspect its saved definition in the conversation and Agents, activate it explicitly, then inspect its ordinary execution history.
4. Select a registered project and sharing scope, request a feature, observe worktree/coding/validation steps, inspect diff and test artifacts in the conversation.
5. Select an installed 27B model, observe loading and GPU allocation, chat with that model, unload only the owned instance.
6. Generate video/avatar/audio using operational installed adapters and receive playable artifacts in the conversation and Library.
7. Restart during planning, dispatch and execution; preserve history and never duplicate an uncertain side effect.

The design above describes the target. Each implementation increment records separately which scenarios were actually exercised.

## Implemented conversation increment

The default screen and new Chat conversations offer Platform assistant mode; Conversation only remains selectable and existing conversations keep their mode. Typed actions cover images, disabled agent drafts and explicitly scoped Cursor tasks. Local model routing handles requests without an explicit action or deterministic match. Invalid plans produce clarification without executing a capability. Ordered image uploads, task-step status, generated images and links to coding/validation Runs appear in the transcript. Repeating an action requires a new user turn rather than completion regeneration.

The first increment reuses the configured inference provider. Managed llama.cpp model selection, model switching during a plan, image understanding, whole-repository coding and media adapters follow as separate increments. Ollama remains supported alongside llama.cpp.

## Speech action

`audio.speech` reads the submitted message in Polish using one uploaded WAV voice reference. It creates an ordinary child Run on the same Task; its output is played inline and remains in the Library. The assistant exposes the action explicitly, can route spoken-text requests with a reference, and clarifies missing references or oversized text. This is speech synthesis, not audio transcription or music generation.

With one portrait and one WAV, the assistant dispatches `avatar.animate` through the ordinary media Run engine and renders the resulting video inline. The selected action can override automatic routing; no media attachment grants additional permissions.

## Reusing Library inputs

The Chat composer can select existing images and PCM WAV recordings from a searchable, paginated Library picker. Image selections retain their click order, with numbered previews and explicit reorder/remove controls before sending. At most eight image references and one voice recording are attached; existing input IDs cannot be selected twice. The ordinary assistant request validates these IDs and records them in Run parameters, preserving artifact lineage without copying or re-uploading files. Trash is excluded from the picker. Upload and text-attachment validation remain unchanged.

Inline image and WAV results also offer **Use as image/voice reference** for the next message. The action stages an existing artifact ID; it does not execute a new task until the user sends the message. Already-attached images and the eight-image limit are reflected in the result controls.
