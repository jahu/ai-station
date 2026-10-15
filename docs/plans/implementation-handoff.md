# Chat/Work and longer media: implementation handoff

Updated 2026-10-15. Implementation is active: the earlier planning-only request and
pause were explicitly superseded. Continue implementation; do not repeat delivered
slices. The live release/image/backup record is
`data/acceptance/safety-redeploy-20261012/deployment.json`; inspect it before deploying.

## Delivered conversation work

- #269: immediate first Send, transactional `/api/chat/turns`, UUID receipts,
  optimistic settings/provider guards, enforced Chat/Work policy, migration 0020.
- #270: separate System and Settings workspaces and typed operator preferences.
- #271: selecting a GGUF performs no inference; Send uses owned load prerequisites
  and discovered GPU indices, preserving larger Coding context requirements.
- #273: Work's Create project & build composes project setup, worktree and proposal,
  with explicit external sharing and typed cancellation of that known chain.
- #274: shared composer/shell, collapsed history/settings/tools, preserved reading
  position and Jump to latest, keyboard/IME behavior and independent Stop.
- #275: one searchable provider/model catalog, metadata-only selection and version
  guards. Installed local models are selectable without manually typing model IDs.
- #276: explicit owned-model thinking qualification, bounded Chat switch, separate
  reasoning events/metadata and collapsed trace; final content/context stay separate.
  Real isolated 9B Off/On and Chat passed. The deployed 9B qualification also passed.
- #277: session draft text, unchanged retry identity across refresh and protection
  of newer text during pending Send. Files/tools are explicitly reselected.
- Current history increment: cursor-paged older conversations and title/message
  search; see [history contracts](../chat-history.md) and acceptance evidence below.

The detailed original UX specifications remain in [chat-work experience](chat-work-experience.md)
and [delivery brief](2026-10-chat-work-media.md). They describe historical findings;
those findings are not proof that delivered APIs/components remain absent.

## Latest delivered increments

- #278–279: paged/searchable history and same-task Work continuation.
- #280–284: durable video/avatar media graphs, full recording timing, Stop/Resume,
  CPU composition, Auto Local coding with verified 100k+ context, conversational
  media progress and restored workspace inputs. Wan carries bounded raw motion.
- #285–286: conversation task-wide Stop with shared startup protection, plus explicit
  existing-task selection in Work without moving the task's original history.
- #287–289: constrained Local Coding JSON and bounded correction of malformed
  read-only exploration. Actual production follow-up succeeded in the same
  RVN 131072-token task/worktree, preserving previous code and passing validation.
- #288: Coding → Work opens a pinned draft; no conversation/Run exists until Send.
- #290: avatar checkpoints retain bounded causal VAE history and flow-step prefix
  preservation. The corrected real 5-second/256/4-step two-window test passed
  complete audio/decode/frame checks and visual seam inspection. Earlier brightness
  failures are preserved, not counted as successful visual qualification.

## Next implementation and acceptance

1. Planner JSON formatting is delivered as #291; actual configured local qwen3:8b planning and response passed. Conversation image-result follow-ups are delivered as #292. GitHub read snapshots are delivered as #293; the Chat/Work tool integration is the current increment, with actual isolated native GH read acceptance.
2. Apply reviewed releases using the central deployment record, preserving idle
   data and native process ownership. A release can include several reviewed PRs;
   retain a healthy Runner when native code is unchanged.
3. Qualify longer avatar/continuous-media profiles only when those exact tests run;
   a 5-second test does not qualify 30/60-second visual quality.
4. Continue the remaining product workstreams in [product completion](../product-completion.md):
   broader multi-step planning/tools, practical coding acceptance, additional media
   runtimes, connectors, and safe node/operations capabilities. Keep unavailable
   integrations explicit and preserve permissions/cancellation/recovery contracts.

## Preserved work and verification

The root checkout `feat/memory-scope-tagged-runs` at `6ba096d` has original Memory
UI/README/architecture/status WIP plus `docs/handoff.md`. Do not reset/stash/stage it.
`.tools/assistant-project-build` retains the original pre-adaptation WIP; the adapted
project-build feature was delivered as #273. Do not redo that original WIP wholesale.

Evidence folders under `data/acceptance/`:
`chat-first-turn-20261014`, `settings-separation-20261014`, `auto-model-20261014`,
`work-project-build-20261014`, `conversation-shell-20261014`,
`unified-model-picker-20261014`, `chat-reasoning-20261014`,
`chat-session-drafts-20261014`, `chat-history-20261014`.
Inspect the recorded final head/results, not a still-running log, before claiming
success. #276 passed 1024 Python tests (five opt-in skips), 383 UI tests, lint/types/
format/build/Compose/Docker and actual isolated 9B reasoning. #277 passed 387 full
UI tests plus five final draft tests and desktop/mobile simulated retry checks;
its backend/native code is identical to #276. Hosted Actions are manual under AGENTS.

Use focused feature branches/PRs to develop and successful local checks for the
reviewed head. Never push/merge main/master. Before applying a reviewed image,
backup the idle application's SQLite DB and preserve original record IDs. Keep a
healthy native Runner when its code is unchanged; upgrade this project's user
service when native code changes. No drivers, model downloads, external runtimes
or unrelated infrastructure changes are authorized by routine development.

Existing-task selection and Coding → Work drafts are delivered (#286/#288);
Migration 0022 stores bindings without moving original Task history. Do not redo
those features or the now-verified same-task local Coding follow-up.

## Delivered recording workflows — 2026-10-15

- #296: offline CPU transcription in Audio and Chat/Work with timestamped TXT/SRT/JSON, lineage, private process ownership and Stop.
- #297: bounded WAV/MP3/M4A/Ogg/WebM/FLAC decoding in memory without external file/URL I/O.
- #298: checked, bounded, quoted transcript context in later conversation turns and summaries; shared compressed-recording validation.
- #299: one Send composes native transcription and the selected-model answer on one Task, freezing provider permissions and preserving transcript artifacts on model failure.
- #300: browser microphone capture with Finish/Cancel, no implicit Send, device cleanup, bounds and retained-file upload retry.

Live #300 release is recorded in `data/acceptance/safety-redeploy-20261012/deployment.json`. Normal API/worker acceptance passed actual CPU transcription plus local Qwen in one Send; Chromium capture was qualified with the approved sample as a fake microphone, not a physical-device test. Existing original-checkout Memory WIP remains untouched. The archive increment adds migration 0024; inspect current reviewed/merged head before deployment.

## Conversation lifecycle and coding providers — 2026-10-15

- #301: reversible archive/restore, active/archived history/search, preserved old URLs and execution/memory records, migration 0024. Actual deployed archive/restore kept all transcript and answer projections.
- #302: persistent Codex/Cursor coding agents reuse the isolated worktree/proposal/validation chain, explicit external profile, source disclosure and approval before children. Actual API/browser activation/approval/denial passed without starting CLI or sending source.
- #303: natural create-project/build requests use the existing qualified 100k+ Auto Local Coding router rather than implicitly inheriting a small Chat model. Explicit model choices remain explicit.

Local coding-agent drafts/editor also support the shared Auto policy; use [agent Auto coding](../agent-coding-auto.md) for enable/launch and approval contracts. Expensive integrations are not implied by fake-provider or metadata/UI acceptance. Current live release remains recorded in the central deployment JSON; inspect it before deployment.
