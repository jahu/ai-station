# Managed local-agent workspaces

A Local coding agent can be enabled without manually registering a repository.
The default is an application-owned private workspace created on its first Run.
Existing projects remain an optional explicit choice; external coding providers
still require a reviewed project and their external sharing permission profile.

The worker composes ordinary Runs on the same agent Task:

1. The reviewed agent workflow publishes a typed `project_setup` Run. Existing
   approval/gated policy applies before any directory is created. All coding-tool
   permissions must still be present; a project association alone grants none.
2. Host Runner creates the repository and Python environment under application
   storage using its existing ownership/path/argv/process contracts.
3. Confirmed completion registers the project and associates it with the agent.
   The original reviewed definition is retained. A derived workflow records the
   exact creation Run, original workflow, project identity and unchanged scope.
4. That bound workflow enters the existing Local coding/worktree path, optionally
   after reviewed HTTP context. No commit, push or deployment is automatic.

The original runtime deadline includes workspace setup, context and coding;
creating a new stage does not reset it. Task Stop reaches setup and all later
stages. Uncertain native completion remains inspectable through existing lease
recovery, without recreating a project or replaying code. If setup finishes after
its deadline, the verified project is retained and linked but coding is not
published; the setup stage fails explicitly. Stale definition saves are rejected
because association updates the agent revision.

Automatic workspaces initially keep dependency installation and automatic checks
disabled. They do not implicitly install packages or widen network access. Project
settings and future typed Python/data workflows retain separate preparation and
execution contracts. This increment provides workspace provisioning, not a claim
that the spreadsheet-agent or website preview milestones are complete.

Normal tests use temporary databases, fake providers and disposable repositories.
Qualification must cover approval, permissions, wrong ownership, snapshot integrity,
expiry, task cancellation, repeated executions and conservative recovery alongside
existing linked-project agent and project-creation tests. Real model/GPU inference
is separate and opt-in.
