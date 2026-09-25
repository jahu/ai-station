# Local agent lifecycle

Persistent agents use the existing Task/Run lifecycle and configured local OpenAI-compatible provider. Draft generation is deterministic and always disabled; the definition, model, selected tools, permissions and UTC schedule must be inspectable before activation. Unsupported tool requests stay visible and block activation rather than silently pretending to execute them.

Initial operational tools are bounded host telemetry and the agent's own scoped memory. These are explicit context-gathering steps before local inference, not an unrestricted model tool loop. No filesystem editing, arbitrary shell, autonomous web access or external AI is granted. Every tool call emits events, and successful output becomes a Markdown artifact. Cancellation closes the model stream; unavailable providers and empty results fail the Run. Definitions are snapshotted when queued; tool observations and model messages are persisted during execution.

Manual, interval, five-field UTC cron and one-shot UTC datetime triggers share the same queue. Schedules persist; only one active Run per agent is allowed. Missed recurring slots are coalesced rather than replayed in a burst. Pausing prevents future launches but does not cancel an already queued/running Run. Explicit Run cancellation remains available.


The Agents workspace supports draft review/editing, explicit enablement, Run now, pause/resume, duplication as a disabled draft, and execution history. Editing requires the expected definition version and no active Run. Pause/resume changes the version; the editor preserves unsaved changes and offers an explicit reload. Tools that the draft parser recognizes but cannot execute remain visible and prevent activation. Other natural-language schedules fall back to manual and must be adjusted in the editor. All cron/one-shot times are explicitly UTC.

The local endpoint comes from administrator configuration, never agent output. The local model uses the shared compatible-provider stream with a bounded output and runtime; host telemetry has an eight-second request timeout. Partial reports are preserved on failure/cancellation. Scheduled Runs have no automatic retry, and missed worker leases become interrupted rather than repeating inference invisibly. A one-shot launch disables its schedule immediately. Interval/cron agents keep their saved cadence when Run now is used.

No external AI, web search, browser, email, file editing, arbitrary shell, or automatic memory writing is enabled in this slice. Agents do not control runtime processes. Existing generic draft adapters remain unregistered.
