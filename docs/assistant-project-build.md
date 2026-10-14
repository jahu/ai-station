# Create and build in one conversation

The platform assistant accepts a new project name, a coding goal and a selected
agent. Local AI is the default; Cursor/Codex require explicit sharing consent.
An explicit `Create project & build` action exposes the name and agent. Auto
recognizes a bounded `Create project NAME and build ...` instruction.

This composes existing Runs on one Task: project setup → isolated worktree →
coding proposal → configured validation. The worker creates the repository and
offline Python environment first. Only confirmed setup completion queues coding;
failed, canceled or uncertain setup never launches a coding provider. No model
inference is needed for this deterministic routing, and a managed model load
remains a prerequisite of the coding consumer rather than project setup.

Scope and model/provider validity are checked before creating the project.
Creation and coding publication share the setup completion transaction, so an
API/worker restart cannot enqueue another task branch from a completed setup.
If coding preparation later fails, the created project remains inspectable.
Media, existing-project scopes and unrelated actions cannot be mixed into this
request. It grants no commit, push, merge or restart permission.

Use **Work → Attach files & choose tools → Create project & build**, enter the
project name and describe the goal in the message. The local agent uses the
conversation's selected model. Cursor/Codex expose their installed model catalog
and require the concrete sharing checkbox; switching agent clears that consent.
Chat rejects this action and its project scope before publishing side effects.
The first Send follows the same idempotent turn API as an ordinary conversation.

The resulting project card opens the identical Coding Task. Existing Coding
continuation and review remain available there. Stop on a just-completed dispatcher
or setup follows validated same-Task setup/worktree/proposal pointers; full graph
Stop and conversational project-context inference remain later increments.

Verification: 1009 backend/Runner tests passed with five explicitly opt-in skips;
375 frontend tests passed before the final form polish, followed by focused Chat,
new-project and action checks. Disposable native repositories/venvs and fake
Local/Cursor/Codex adapters cover setup, proposal, ownership, no replay, preflight
failure preserving the project and setup-boundary cancellation. UI evidence is
under `data/acceptance/work-project-build-20261014`. No real external-provider
project build or new long-media smoke is claimed by this feature.
