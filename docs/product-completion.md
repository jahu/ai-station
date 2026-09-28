# Full-product acceptance ledger

The development target is the complete AI Station vision, confirmed on 2026-09-27. Earlier local-MVP reports describe verified milestones; they are not the completion definition. A capability is complete only when its UI, persisted state, execution/permissions, cancellation/recovery, artifacts and applicable real integration have been verified. A percentage is not a substitute for these checks.

| Workstream | Implemented foundation | Next acceptance increments |
| --- | --- | --- |
| Coding and Git | Owned worktrees, Cursor selected-file changes, diff and validation | Reviewed commits; approved push/PR to integration; whole-repository tools/iterations; Codex, local and Claude adapters; repeatable project dependency setup; worktree lifecycle |
| Agents and workflows | Persistent local agents, schedules, telemetry/memory tools | General tool calling, durable approvals, bounded workflow steps, retry/notification policies, versioned Skills and natural-language factory expansion |
| Chat and routing | Local compatible providers, streaming, history, summaries, text files | Provider registry/secrets, external providers with explicit selection, vision/document inputs, automatic context maintenance, universal task router and execution-mode overrides |
| Media | Existing image pipeline and library | Managed video, speech, music and avatar adapters, real runtime/model selection and shared artifact lineage |
| Models and runtimes | Model discovery, external observations, owned multi-GPU llama.cpp, automatic reload and idle eviction | Broader runtime adapters, model definitions/presets/compatibility, explicit installation, extended process controls and health |
| Connectors and tools | Registry/permission foundations | HTTP/search/browser, GitHub and user-configured email/calendar/social integrations, secret references, audit and approvals |
| Memory | Scoped provenance, FTS, pinned context and explicit summaries | Workflow/agent memory production, managed rolling context, optional embeddings with explicit model setup |
| Nodes and operations | Portable local Docker control plane and private native Runner | Authenticated node registration/transport, target-aware resources, authentication before LAN exposure, packaging/upgrade/recovery and long-running reliability |
| UX and observability | Workspaces, command palette, Runs/events/artifacts, telemetry | Unified actionable activity, rich coding review/actions, keyboard workflows, accessibility and end-to-end acceptance across enabled capabilities |

All increments retain Task → Run → Events → Artifacts, typed runner operations, explicit permissions, protected release branches and data-preserving upgrades. Credentials, host changes or external account actions are requested only when actually needed for a concrete integration; routine implementation continues independently.

## Current priority: one conversation operates the workstation

The user-facing default is a platform assistant, preserving Images, Coding, Agents and all other dedicated workspaces. See [orchestration design](orchestrator.md). Implementation order: durable conversation actions and inline results; selectable on-disk LLMs with owned runtime lifecycle; richer project/agent tool loops; installed video/avatar/audio integrations; remaining acceptance increments above.
