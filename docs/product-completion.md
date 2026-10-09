# Full-product acceptance ledger

The development target is the complete AI Station vision, confirmed on 2026-09-27. Earlier local-MVP reports describe verified milestones; they are not the completion definition. A capability is complete only when its UI, persisted state, execution/permissions, cancellation/recovery, artifacts and applicable real integration have been verified. A percentage is not a substitute for these checks.

| Workstream | Implemented foundation | Next acceptance increments |
| --- | --- | --- |
| Coding and Git | Name-only managed projects, persistent coding conversations, owned worktrees with explicit removal and unused automatic expiry, Codex/Cursor/local-model changes, automatic source exploration, explicit and bounded automatic repair after failed validation, unique snippet replacements or complete selected-file rewrites, cumulative diff, validation, repeatable sandboxed Python dependency install, reviewed commits and approved draft GitHub PR publication with explicit GitHub outcome reconciliation | Claude adapter |
| Agents and workflows | Persistent local agents, schedules, telemetry/memory/search tools, reviewed public HTTP GET and report/source inspection, versioned Skills as instruction packs | General tool calling, durable approvals, bounded workflow steps, retry/notification policies, natural-language factory expansion |
| Chat and routing | Local compatible providers, streaming, history, opt-in automatic summaries, text files, PDF text extraction and stored image artifacts without pixel vision, provider registry with secret references and explicit local/external selection | Vision-capable inputs, universal task router and execution-mode overrides |
| Media | Existing image pipeline, local Chatterbox speech, EchoMimic portrait video, inline media workspaces and searchable Library with annotations and reversible Trash | General video and music adapters, real runtime/model selection and shared artifact lineage |
| Models and runtimes | Model discovery, external observations, owned multi-GPU llama.cpp, automatic reload and idle eviction, assistant load/unload of owned instances | Broader runtime adapters, model definitions/presets/compatibility, explicit installation, extended process controls and health |
| Connectors and tools | Registry/permission foundations and optional public search | HTTP/browser, GitHub and user-configured email/calendar/social integrations, secret references, audit and approvals |
| Memory | Scoped provenance, FTS, pinned context, manual and opt-in automatic summaries and agent report memory | Workflow memory production, oversized-message chunking, optional embeddings with explicit model setup |
| Nodes and operations | Portable local Docker control plane and private native Runner | Authenticated node registration/transport, target-aware resources, authentication before LAN exposure, packaging/upgrade/recovery and long-running reliability |
| UX and observability | Workspaces, command palette, Runs/events/artifacts, telemetry, assistant coding review/commit/publish in the conversation | Unified actionable activity, remaining keyboard workflows, accessibility and end-to-end acceptance across enabled capabilities |

All increments retain Task → Run → Events → Artifacts, typed runner operations, explicit permissions, protected release branches and data-preserving upgrades. Credentials, host changes or external account actions are requested only when actually needed for a concrete integration; routine implementation continues independently.

## Current priority: one conversation operates the workstation

The user-facing default is a platform assistant, preserving Images, Coding, Agents and all other dedicated workspaces. See [orchestration design](orchestrator.md). Implementation order: durable conversation actions and inline results; selectable on-disk LLMs with owned runtime lifecycle; richer project/agent tool loops; installed video/avatar/audio integrations; remaining acceptance increments above.
