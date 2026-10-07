# Local agent lifecycle

Persistent agents use the existing Task/Run lifecycle and configured local OpenAI-compatible provider. Draft generation is deterministic and always disabled; the definition, model, selected tools, permissions and UTC schedule must be inspectable before activation. Unsupported tool requests stay visible and block activation rather than silently pretending to execute them.

Operational tools are bounded host telemetry, the agent's own scoped memory and explicitly configured public web search. These are explicit context-gathering steps before local inference, not an unrestricted model tool loop. No filesystem editing, arbitrary shell, autonomous web access or external AI is granted. Every tool call emits events, and successful output becomes a Markdown artifact. Cancellation closes the model stream; unavailable providers and empty results fail the Run. Definitions are snapshotted when queued; tool observations and model messages are persisted during execution.

Manual, interval, five-field UTC cron and one-shot UTC datetime triggers share the same queue. Schedules persist; only one active Run per agent is allowed. Missed recurring slots are coalesced rather than replayed in a burst. Pausing prevents future launches but does not cancel an already queued/running Run. Explicit Run cancellation remains available.


The Agents workspace supports draft review/editing, explicit enablement, Run now, pause/resume, duplication as a disabled draft, and execution history. Editing requires the expected definition version and no active Run. Pause/resume changes the version; the editor preserves unsaved changes and offers an explicit reload. Tools that the draft parser recognizes but cannot execute remain visible and prevent activation. Other natural-language schedules fall back to manual and must be adjusted in the editor. All cron/one-shot times are explicitly UTC.

The local endpoint comes from administrator configuration, never agent output. The local model uses the shared compatible-provider stream with a bounded output and runtime; host telemetry has an eight-second request timeout. Partial reports are preserved on failure/cancellation. Scheduled Runs have no automatic retry, and missed worker leases become interrupted rather than repeating inference invisibly. A one-shot launch disables its schedule immediately. Interval/cron agents keep their saved cadence when Run now is used.

No external AI, browser, email, file editing, or arbitrary shell is enabled in this slice. Agents do not control runtime processes. Existing generic draft adapters remain unregistered.

## Scheduled internet research

Select **web_search**, enter a **Public search query**, save the definition and then enable the agent. The query is required before activation; it is never inferred from the private goal or memory. Each manual or scheduled Run snapshots the query and `network_read` permission, uses the same bounded SearXNG tool as Chat, and persists source URLs, snippets, timestamps and a JSON artifact before local inference. Tool availability reflects actual provider configuration. Existing drafts remain disabled after migration.

The worker enforces cancellation and the overall agent deadline while searching. Search failure stops the Run rather than generating a report without the requested evidence. Search snippets are untrusted context, not instructions or page contents. Run details display the full Markdown report, partial-output labeling and independently recorded clickable source cards. External Markdown images are not loaded.

Both draft creation and definition editing reuse Chat's searchable local-server/llama.cpp model picker, including saved multi-GPU presets. Scheduled executions use the existing owned-runtime scheduling path. Each execution creates a report; change-only notification policies and arbitrary browser research are not implemented.

Verified 2026-09-30: real Chromium definition editing → private SearXNG public search → existing multi-GPU llama.cpp 27B → Polish report and recorded source cards. Run `cb11cc6e-721d-4a86-acb6-294071c8ea27` used an isolated database; the report survived an API restart. Manual and scheduled query snapshots, cancellation, deadlines, permissions, migration and UI behavior also have automated coverage.


## Remembering reports

Select **Remember reports** in the definition to grant scoped `memory_write`. Every successful manual or scheduled Run stores an observation in that agent's own memory with source Run provenance. Select **memory_search** separately to include previous enabled memories in future reports. Neither option is enabled implicitly; stored observations are not verified facts and are never promoted to global memory.

Run details link directly to the saved entry. Memory supports editing, disabling and deleting it. Reports longer than 12,000 characters retain an explicitly labeled excerpt; the full Markdown artifact remains available. Saving memory and marking the Run successful share a database transaction. Failed or canceled Runs preserve partial report artifacts but create no memory. Worker recovery never silently retries the write or inference.
