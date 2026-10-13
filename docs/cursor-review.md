# Cursor review and completion plan

Reviewed on 2026-10-13 against `develop` at 8688a30, with the running deployment checked separately. Cursor's unfinished Memory edits in the original checkout are preserved and are not part of that release.

## Findings and repairs

- **Data loss risk:** scheduled worktree expiry could force-remove dirty worktrees and unmerged branches after seven days. PR #245 disables automatic expiry, rejects old scheduler removal Runs and requires explicit user removal. Regression coverage preserves dirty files, untracked files and unmerged commits.
- **UI freezes:** synchronous operator-session SQLite lock waits blocked the API event loop. PR #246 moves them to the thread pool. A real-lock regression proves unrelated requests remain responsive.
- **Deployment drift:** the preview was running an older release despite many merged changes. The current release is deployed from an isolated checkout, migrations were rehearsed, the database was backed up and original record counts were preserved.
- **UX regression:** the Chat start screen exposed every setting and the assistant composer expanded sixteen action radios plus implementation-oriented help. The next repair keeps model selection and conversation creation prominent, puts optional settings behind progressive disclosure and uses a compact accessible action picker.
- **Completion reporting:** many later Cursor increments improve keyboard navigation and cross-links. Those changes do not complete missing execution adapters. The acceptance ledger now separates operational capabilities from pending delivery instead of enumerating every keyboard control.
- **Formatting debt:** the reviewed baseline has 59 frontend Prettier failures. Existing lint, typecheck, tests and production build pass; formatting must be repaired without mixing it into execution changes.

The NVML failure was a mismatch between the loaded kernel driver and upgraded user-space libraries. After the separately authorized reboot, both report 595.99.02 and both 12 GiB RTX 3060 GPUs are detected. This is not evidence that either card failed; no GPU stress or inference test was performed as part of that check.

## Delivery order

1. Repair the conversation UX and close the baseline formatting check.
2. Make the platform assistant operate actual workstation state and carry bounded conversational context; preserve explicit coding, publication and runtime permissions.
3. Complete real media/vision and coding adapter acceptance, with model and resource selection visible.
4. Extend operational agent tools and connectors through the shared queue and approvals.
5. Complete safe restore/rollout and authenticated node transport, then run end-to-end acceptance across the product.

Each step needs an actual working integration, appropriate tests, a reviewed feature PR into `develop` and a data-preserving deployment. Unimplemented adapters are not advertised as operational. Details and remaining acceptance criteria live in [product-completion.md](product-completion.md).

## Verified baseline

696 backend/runner tests passed; 5 expensive integrations were explicitly skipped. The preceding frontend verification passed 339 tests, lint and typecheck; the deployed Docker image includes a successful TypeScript/production build. Six workspaces loaded and reloaded with correct headings and no browser or server errors. This does not establish real generation success for every model or media mode.

Local preview: http://127.0.0.1:8765/ . Evidence and preserved database copies are recorded in the local ignored `data/acceptance/safety-redeploy-20261012/` directory.

## Completed follow-up — 2026-10-13

PR #247 repaired the conversation start screen and compact assistant action selection. PR #249 fixed the frontend formatting debt without changing TypeScript/JSX behavior. PR #248 added a real, read-only workstation inspection action and immutable bounded follow-up context; both GPU cards appear in the saved Chat report. These changes are deployed under the local preview URL above.

Further model review found that the context heuristic inferred KV storage from weight-file size. The current repair uses bounded GGUF attention metadata in the load worker. Real acceptance now confirms a local 27B model with 131072 context, a completed 110029-token input and an isolated local Coding proposal with passing unittest validation. This follow-up changes the inference verification status; the earlier reboot check itself did not run inference. The full product acceptance ledger remains open.

## Local image understanding follow-up — 2026-10-13

The default assistant now reads actual attached image pixels using an installed local vision GGUF/projector pair. Runtime selection, owned model loading, streaming and source-linked description artifacts use ordinary Runs. A real isolated Qwen 9B smoke correctly recognized two colored shapes. This closes the earlier filename-only image inspection gap; practical editing and broader media acceptance remain in the ledger.

## Coding agent follow-up — 2026-10-13

Persistent agents now have an explicit Local coding tool bound to a reviewed project and local model. It delegates to the existing owned worktree, exploration, proposal and validation workflow. Child cancellation, deadlines, notices and manual retry preserve that chain; an opted-in real 9B task passed configured unittest validation. Results remain available for review and continued Coding prompts, with no automatic commit/publication.
