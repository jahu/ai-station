# Chat/Work and longer media: implementation handoff

Updated 2026-10-15. Implementation is active: the earlier planning-only request and
pause were explicitly superseded. Continue implementation; do not repeat delivered
slices. The live release/image/backup record is
`data/acceptance/safety-redeploy-20261012/deployment.json`; inspect it before deploying.

## Current implementation — website agent build policy, 2026-10-22

PR #337 is merged as `e13632e` and deployed. Its native/UI/image rollout passed
LAN/loopback authentication, all persisted IDs/password, 3 worker slots,
scheduler/socket/source identity and preservation of the operator's actual model
container/context. Current release:
`.tools/ui-agent-site-preview-20261022`; actual deployment state remains in
`data/acceptance/safety-redeploy-20261012/deployment.json`.

Continue `feat/agent-owned-site-workspace` in `.tools/agent-owned-site-workspace`.
Automatic private project setup already existed; do not reimplement it. The new
increment fixes absent build output by adding reviewed `workspace_policy` flags
to Agent definitions (migration **0028**) and forwarding them to the existing
setup/dependency/check pipeline. Factory proposes them for explicit Local website
requests, still disabled pending activation. Existing definitions default off;
linked project policy remains authoritative. Agent settings/conversation cards
show the possible public package downloads. Exact frozen setup policy, tool
boundaries, API round-trip/duplicate and legacy migration tests passed. Current
focused coverage: 133 Python and 80 UI tests; compiled desktop/mobile review/save/
reload passed without models/workers. See [policy](../agent-website-build-policy.md).

Full regression/review and the actual website generation/build/preview follow-up
still remain. Do not claim real-model acceptance from these fixture checks, and
preserve the operator-selected 27B Q4 instance at its current 46080 context. Root
checkout WIP is untouched. Any eventual 0028 rollout verifier must update its
expected schema head and compare fresh ready model instances; native source is
unchanged from PR #337, so no Runner restart is needed for this increment.

## Earlier preview candidate — 2026-10-22

PR #337 has final successful local qualification: 1830 Python tests/eight opt-in
skips; 523 UI tests; format/lint/types/build; Compose/image; exact image/backend
and frontend asset equality; and actual CPU worker/socket/Chromium plus compiled
desktop/mobile acceptance. See [preview evidence](../agent-site-preview.md).
Production rollout is tracked separately in
`data/acceptance/safety-redeploy-20261012/deployment.json`; never infer that the
candidate has been applied from this document alone. The guarded deploy script
under `data/acceptance/agent-site-preview-20261022` requires the PR to be merged,
a fresh snapshot of ready managed models, an idle native process owner and a DB
backup before replacing this project's containers/Runner. Preserve the separately
operator-loaded model/context. Next: reviewed-URL website-agent end-to-end
acceptance, then typed recurring quote observations and scoped email delivery.

## Earlier delivery — 2026-10-22

PR #332 (context-aware follow-up search and remembered default-on Chat search)
is merged and deployed. Production identity and persistence checks passed; see
`data/acceptance/chat-contextual-search-20261015/deployed-verification.json`.

The active feature is `feat/python-data-agents` in `.tools/python-data-agents`.
It includes persisted input scope (migration 0027), local source generation,
automatic private worktrees, offline CPU Python execution, bounded repair,
verified result/table/CSV artifacts and Agent/conversation UI. CSV and genuine XLSX acceptance
passed with the installed 27B IQ2_XS model at verified 131072 context and an actual
Python container. The acceptance freezes an already-loaded real model binding;
it does not prove production automatic loading for this new workflow. Original
input bytes remained unchanged and the test model was unloaded afterward.

Compiled desktop/mobile checks passed result/download/reload and draft
duplication/upload/save without running an agent or model. Genuine XLSX also
exercised one real bounded repair before success. Remaining before delivery:
combined regression checks, final PR review, migration/Runner/image rollout and
production smoke. Do not mistake the earlier executor-only handoff or
old status files for this feature's current result. Preserve root WIP. Do not
restart the user-selected model just to inspect UI; acceptance-only model loads
must be unloaded afterward if the original station was idle.

## Current priority override — 2026-10-15

Read [agent-first product direction](agent-first-product.md) before choosing work.
The user explicitly deprioritized large-project IDE development and expanding
Cursor/Codex integrations. Keep their services/records intact. Next implement a
typed isolated local Python execution tool for agents and an XLSX/CSV result flow,
then agent-oriented workspace/results and website acceptance, then recurring typed
price observations with scoped real email delivery. Container isolation now serves
agent scripts; full AI Station self-suite acceptance is deferred as a product goal.
Coding navigation changes follow working replacement views and preserve old tasks.

PR #323 is merged/deployed at `8a04874`; local release evidence is under
`data/acceptance/self-development-validation-20261015`. Its component preparation,
source isolation and installer fixes remain useful shared agent infrastructure.
Earlier self-development prioritization below is superseded by this decision.

## Active agent Python execution increment

`feat/agent-python-execution` in `.tools/agent-python-execution` implements the
[execution contract](../agent-python-execution.md). Native API/schema, frozen
worktree/input snapshots, optional CPU image, bounded container protocol,
Stop/cleanup and source/output/report Artifact adoption are implemented. A real
isolated disposable test passed CSV/XLSX processing, network denial, read-only
inputs, required-output failure, Stop and deadline cleanup with the original
repository untouched. Focused executor tests pass; full regression/review is
pending. Local evidence: `data/acceptance/agent-python-execution-20261015`.

This is the execution component, not a completed user-facing spreadsheet agent.
Next wire local script generation, automatic managed workspace setup, declared
input upload/inspection and results into agent workflows/UI. Do not publish an
operational agent tool or remove Coding navigation before those paths work.
Current deployed release remains `8a04874`; it needs no restart for this work yet.

## Earlier work (historical)

PR #322 is merged and deployed as `35ab4a4`. Final code passed 1576 Python tests
(five opt-in skips), 488 UI tests, lint/format/types/build, Docker/Compose and
actual saved-scene/Stop/restoration inspection at 1440/390/320. Real production
graph/receipt/Stop checks canceled every QA stage before owned worker restart;
no storyboard GPU dispatch or model eviction occurred. The same restored 27B
runtime remains ready. Evidence: `data/acceptance/video-storyboard-20261015`.

Active work is `fix/self-development-validation` in `.tools/self-development-validation`.
The component-environment implementation adds explicit development locks, nested
Node preparation, owned Python source imports and bounded validation deadlines to
existing project Runs. A disposable real Cursor-sandbox probe passed offline pip,
nested npm installation/build and owned-source import while preserving the original
checkout. It also exposed and fixed project `pip.py` shadowing and missing exact
public OS/MIME metadata reads. PR #323 passed 1597 Python tests (five opt-in skips), 489 UI tests, Ruff, frontend
format/lint/types/build, Docker/Compose, disposable migration round-trip and
compiled browser checks at 1440/390/320. The final UI toggle correction preserves
identical backend/Runner source to the full-suite head. Review/deployment state is
recorded with the release record above; do not assume a restart from this document. Evidence is under
`data/acceptance/self-development-validation-20261015`.

Full AI Station self-suite execution remains the next increment: the native
sandbox denies host process observations needed by process-ownership tests. Use a
controlled container target with a private PID namespace instead of granting host
`/proc` or broad temporary access. The real Self project still has syntax-only
commands. Preserve root WIP; current production Runner remains on #321 until a
reviewed release is deployed. Earlier sections below are historical.

PR #321 is merged/deployed as `3783ba6`: GPU-wait queue fairness and startup native
source compatibility. Verification passed 1567 backend/Runner tests (five opt-in
skips), Ruff, Docker/Compose and actual desktop/mobile persistence checks. Actual
native observation confirmed the same ready 27B container and 131072 context after
that deployment. Evidence: `data/acceptance/runner-source-compatibility-20261015`.

PR #322 (`feat/video-storyboard`, `.tools/video-storyboard`) is ready for final
review/merge/deployment after 1576 backend/Runner tests (five opt-in skips), Ruff,
488 UI tests, final format/lint/types/build, Docker/Compose and private compiled
browser checks at 1440/390/320. Native source is unchanged from #321. See
[the scene plan](../video-storyboard.md); evidence is in
`data/acceptance/video-storyboard-20261015`. Preserve original root WIP.

The real 30-second 384-pixel/eight-step avatar is complete. Full decode and
browser playback passed; sampled joins are continuous, while appearance/hand
artifacts remain visible with the full-body QA input. Scope and remaining visual
qualification are in [the acceptance record](../long-avatar-qualification.md),
with local evidence under `data/acceptance/long-avatar-default-20261015`. The
original owned 27B preset is restored at actual 131072 context on both GPUs.
The station is idle again; retain its healthy native service for the #322 rollout.

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

## Latest integration — 2026-10-15

- #304: Local coding-agent drafts and the editor use the shared fitting 100k+
  Auto policy, with approval before any model/worktree execution.
- #305: positioned table scroll containers keep hidden table headers from
  widening the mobile Runs page. All 16 workspaces passed desktop/mobile reads.
- #306: explicit current-turn Polish/English named-project change instructions
  resolve to Local Coding Auto. Scope revisions, Chat boundaries, receipt replay
  and Stop are tested; UI Send passed without new inference.
- #307: conversation header controls wrap without stretching/clipping. Narrow
  and short windows use normal page height plus a bounded transcript; actual UI
  Stop passed on five viewport sizes.
- Current reviewed-page coding increment composes explicit public HTTP reads,
  verified source artifacts and the normal isolated Local coding chain. Read
  [the contract](../agent-page-coding.md) before changing its boundaries. Real
  public HTTPS and browser setup/Stop passed; no new real coding inference is
  implied by those checks. Final combined validation is recorded in
  `data/acceptance/agent-page-coding-20261015`.

Always read the central deployment JSON for the actual live release rather than
assuming an older milestone mentioned above is still running. The original root
checkout's Memory WIP remains preserved separately; local `develop` is checked
out in the owned `.tools/chat-reasoning` worktree and should be fast-forwarded
only when tracked-clean and inactive. Never reset the root checkout to deploy.


## Node projects — 2026-10-15

- #308 delivers reviewed public-page context before Local coding.
- #309 delivers checked npm v3 dependency installation, configured Node/npm
  runtime diagnostics, sandboxed Node validation and a project-local installer.
- The current missing-lock increment stages offline npm resolution and primes
  only checked public-registry metadata through a typed pinned-IP/TLS client.
  Missing optional package metadata is filled before success; the final checked
  lock is exclusively published without overwriting existing project files.
  Actual no-lock is-odd/transitive and React 19/Vite 7 builds passed, including
  lifecycle/file/Git boundaries. See [Node dependencies](../node-project-dependencies.md).

Use the central deployment JSON for the actual active release and retain the
original root Memory WIP. The missing-lock increment is not delivered until its
full checks, reviewed PR to develop and deployment verification are recorded.

## Next active implementation: automatic managed-project checks

#310 is merged into develop as 9aad0e7. Its reviewed source passed 1418 Python
and 451 frontend tests, Compose/Docker, desktop/mobile UI, and actual no-lock
React 19/Vite 7 installation plus production build with 67 checked packages.
Evidence: data/acceptance/node-lock-generation-20261015. Read the central deployment
record for the actual active release; original Memory WIP remains untouched.

Continue in the owned feat/coding-auto-project-checks worktree. Implement the
planned automatic preparation/check contract in docs/coding-boundary.md. The
concrete gap is that new managed projects have empty validation commands and the
coding proposal currently queues validation directly, without dependency setup.
Use frozen explicit project policies, the same Task/child-Run graph, tested typed
installers and saved-command authority. This increment is not implemented yet;
do not mark the overall platform goal complete or claim LLM-generated React
acceptance from the manually prepared #310 fixture.


## Automatic project checks implementation in progress

The feat/coding-auto-project-checks worktree implements migration 0025, persisted
opt-in project policies, frozen Coding/Work/agent snapshots, bounded typed native
planning and same-Task dependency/check gating. New managed UI defaults are
explicit; existing/old snapshots remain manual. Actual React/Vite automatic
plan→install→build passed with a synthetic coding source. Do not claim a real
LLM-generated website from that evidence. Acceptance is under
`data/acceptance/coding-auto-project-checks-20261015`. Complete full checks, browser
review, PR to develop and deployment before marking this increment delivered;
then perform the actual one-conversation local long-context coding smoke.

## Automatic project checks delivered; practical acceptance follow-up

PR #311 is merged as `642b166` and deployed from
`.tools/ui-coding-auto-project-checks-20261015`. Migration 0025, 1436 Python
tests (five explicit opt-in skips), 452 frontend tests, frontend lint/types/build,
Compose and Docker passed. Browser checks passed all 16 live workspaces on
desktop/mobile. Original database IDs are preserved.

Actual Work task `0d0e7756-2498-4482-bf08-2e96fabfa89d` created a managed React
project and loaded Local Auto through owned llama.cpp. Exploration failed on
`.gitignore`; no generated website or successful validation is claimed for this
attempt. Continue in `fix/coding-gitignore`, preserve its existing worktree and
original failure, then requalify real tests/build after the reviewed fix.
Evidence: `data/acceptance/coding-auto-project-checks-20261015`.

## Root ignore fix delivered; current frontend increment

PR #312 is merged as `b13ae5e`, deployed and native Runner source verified.
1453 backend/Runner tests (five opt-in skips), 452 frontend tests, lint/types/format,
Compose and Docker pass. Real Work continuation now passes local inference,
automatic dependency installation, a real React rendering test and Vite build
in the original owned worktree; original project files/index are preserved.
Keep the initial failed attempt in history. Evidence is under
`data/acceptance/coding-gitignore-20261015`.

PR #313 (`feat/coding-task-progress`) adds a read-only stage summary in Coding.
It distinguishes code completion from checks, missing tests, earlier failed
attempts, install failures, approval and Stop. Backend/native code matches #312.
Finish the final frontend checks, responsive browser review and Docker build,
review the complete PR, merge to develop and apply the reviewed image when idle.
Then continue practical Coding/Work usability, safe artifact/build inspection and
the remaining product workstreams. The broad platform goal remains active.

## Current active increment: Coding build artifacts

PR #313 is merged as `ffed73d` and deployed from
`.tools/ui-coding-task-progress-20261015`; the healthy identical-source native
Runner was retained. Final checks: 463 frontend tests, format/lint/types/build,
Docker/Compose, desktop/mobile browser review, all 16 live workspaces and the
actual successful Coding task. Backend/Runner matches #312's 1453 passing tests
(five opt-in skips). Original database IDs and root Memory WIP are preserved.

Continue `feat/coding-build-artifacts` in `.tools/coding-build-artifacts` using
[coding-build-artifacts.md](../coding-build-artifacts.md). Deliver normal build
Artifacts and a Download build/Library action, keeping untrusted HTML as data.
Do not regenerate the already-qualified React site merely to test exporting it.
The broad platform goal remains active; no final product completion is claimed.

Build artifact implementation is now in `feat/coding-build-artifacts`: bounded
no-follow ZIP capture in native validation, checked ordinary Artifact registration
and Download build/Library UI. Focused native/backend tests pass (43); complete
required full checks, real sandboxed export using the existing QA React site,
responsive UI review, PR review/merge and deployment before marking delivered.
No new inference is needed to qualify exporting the existing site.

## Build output reviewed; Coding draft delivery

PR #314 is merged as `f08f859`: build ZIP Artifacts, native child draining, checked
registration and Coding/Work Download build + Library links. Required checks
passed on `f2ce119`: 1497 backend/Runner tests (five opt-in skips), 466 UI tests,
format/lint/types/build, Docker/Compose, real sandboxed React validation/export
without new inference, and desktop/mobile download/Library inspection.
Deployment is pending the combined Coding draft increment.

`feat/coding-conversation-drafts` adds task-scoped unsent text, refresh/navigation
restore, guarded Ctrl/Cmd+Enter, isolated consent and preservation of newer edits
during pending Send. 472 frontend tests and responsive browser checks passed;
Send was intercepted in browser qualification, so no extra coding execution is
claimed. Merge the reviewed UI PR and deploy the combined image once, restarting
the own native Runner for #314. Preserve root Memory WIP and all original data.

Next practical gap: re-run checks on an existing Coding turn without invoking a
model. Projects can validate worktrees, but Coding lacks a same-Task action that
preserves earlier check history and refreshes the visible artifact/check result.
Implement it with trusted project commands/policies, owned worktree/active-Run
guards, clear provenance, Stop and conservative recovery. Do not fake Run/source
records in production or regenerate the qualified React site just to test export.

## Current active increment: repeat Coding checks

PRs #314/#315 are merged and the combined `71203e7` release is deployed. Original
IDs and the original checkout WIP are preserved. The production API/worker/native
Runner passed a real saved React test/build/export, with ZIP visible in Library.
No new inference was performed. Evidence is in
`data/acceptance/coding-drafts-20261015/production-export-result.json`.

Continue `feat/coding-rerun-checks` in `.tools/coding-rerun-checks` using
[coding-rerun-checks.md](../coding-rerun-checks.md). This increment is planned,
not implemented. It must repeat an existing Coding validation on the same Task,
without model inference, automatic repair or dependency installation, with
history, race/ownership guards and fresh manual Stop semantics. Then continue
the broader product workstreams; the platform goal is still active.

Check reruns are implemented in `feat/coding-rerun-checks` (not yet merged or
deployed): atomic expected-validation/source/project guards, same-Task frozen
check snapshots, fresh manual Stop semantics and a manual-only flag preventing
automatic LLM repair. Coding progress and Coding/Work review expose the action
and preserve the current draft. Focused backend tests pass (22). Complete full
checks, real sandbox/browser acceptance, PR review/merge and deployment before
marking delivered. Reuse the qualified QA React task without new inference.

## Current active increment: Coding continuation after builds

PR #316 is delivered as `94d1036`, with live same-Task Node test/build repetition
and a new ZIP, no model/dependency Runs, retained history and unchanged original
checkout. Evidence: `data/acceptance/coding-rerun-checks-20261015/production-result.json`.

Continue `fix/coding-continuation-review` in `.tools/coding-continuation-review`.
[The plan](../coding-continuation-review.md) records an actual blocker: 1155
internal untracked scratch files and a 32265-byte generated lockfile in the QA
worktree collide with the current selected-context limits during cumulative
review/commit. Fix source scanning and separate bounded review from inference
context, with report-size preflight and the existing path/write protections.
Implementation is on PR #317. Focused native and follow-up integration tests pass,
including generated locks, 15-file commit, tracked credential rejection and encoded
report preflight before writes. Full backend/Runner checks and deployment acceptance
are pending; do not report production acceptance until evidence is recorded in
`data/acceptance/coding-continuation-review-20261015`. Preserve scratch data and root WIP.


## Next increment: larger Local Coding source context

PR #317 is deployed and real-tested; see the delivered section in
[coding continuation](../coding-continuation-review.md). Continue in
`.tools/coding-source-windows` on `feat/local-coding-source-context`, following
[the bounded local context plan](../local-coding-source-context.md).


## Current: finish preserved Memory scope navigation

PR #318 is merged/deployed and qualified: full 1547-test suite plus actual
110 KB synthetic local Work edit, Node/build and desktop/mobile acceptance.
See [delivered evidence](../local-coding-source-context.md#delivered-acceptance--pr-318).
Continue in `.tools/memory-scope-navigation`, `feat/memory-scope-navigation`,
following [scope navigation](../memory-scope-navigation.md). Root WIP stays
untouched; only its focused frontend change was ported.


## Current increment: independent video shots

Memory scope navigation is delivered in #319 (`e10366c`): full 480-test frontend
validation, Docker/Compose, identical qualified #318 backend/Runner, existing
agent-memory → agent/filtered history browser acceptance at 1440/390, no writes.
Evidence: `data/acceptance/memory-scope-navigation-20261015/review.json`.

Continue `.tools/parallel-video-shots`, `feat/parallel-video-shots`, following
[the parallel shot plan](../parallel-video-shots.md). Preserve conservative RAM
admission and current 27B runtime; do not claim unexecuted multi-GPU smoke tests.


## Current: media resource wait fairness

PR #320 is merged/deployed and verified (see delivered evidence in
[parallel video shots](../parallel-video-shots.md)). PR #321 now combines
[resource wait fairness](../media-resource-wait-fairness.md) and
[native source compatibility](../runner-source-compatibility.md) for one reviewed
rollout. Both originally failing regressions are fixed: 35 queue/media tests and
10 launcher/source/private-socket tests pass. Full combined checks on `bd897aa`
passed: 1567 tests, five explicit opt-in skips, Ruff lint/format. Docker image and
both Compose configurations passed. Later changes are documentation-only;
rollout is pending. The earlier standalone queue full run ended with signal 143 and
no pytest terminal summary, and is not counted as passed. Frontend is unchanged
from qualified #320. Preserve all root WIP, data and the current 27B runtime.

Review/deployment evidence is under
`data/acceptance/runner-source-compatibility-20261015`; queue regression evidence
remains in `data/acceptance/media-resource-wait-fairness-20261015`. Deploy only after
full checks pass, using the prepared idle-only owned Runner restart, a verified
SQLite backup, and post-start exact source/image/persistence checks. The broader
platform goal remains active; this PR is not a claim of full-product completion.


## Current owner request: private phone access (2026-10-15)

Follow [private network access](../private-network-access.md) and the owner’s updated [agent-first priorities](agent-first-product.md). PR #326 adds an explicit additional private IPv4 listener while preserving localhost, a password-required startup guard, exact Host/Origin validation, independent device sessions and a persistent login budget. Settings exposes the configured URL. Real browser qualification covers both listener addresses and narrow phone layouts; keep failed QA attempts in the evidence instead of claiming them passed. Tailscale is not installed/enrolled; the HTTPS allowlist and activation instructions are preparation, not real worldwide access acceptance.

Worktree `.tools/private-network-access`, branch `feat/private-network-access`. Evidence is under `data/acceptance/private-network-access-20261015`. Preserve the user’s newly stored operator password, root WIP and current owned model runtime. Before rollout, finish local checks and full-diff review, back up the existing database and verify deployment ownership/idle workloads. After rollout, resume the Python-capable agent vertical slice; PR #325 is the isolated executor foundation, not a complete spreadsheet agent.


## Current: agent workspace and isolated site preview (2026-10-22)

PR #334 fixed the exact data-input environment/repair ambiguity; #335 delivered
results-first agent Workspace/Settings; #336 embedded the existing code
conversation, review and follow-up composer in that workspace. All are merged
into develop and deployed. Latest release is `.tools/ui-agent-code-workspace-20261022`
(reviewed `253adee`, merge `d0604ed`), with verified LAN/loopback authentication,
worker/scheduler health, backup and preserved original records. Backend/Runner:
1717 passed, five opt-in skips; final frontend: 516 passed, format/lint/types/build,
Compose/image and desktop/mobile browser acceptance. Evidence is under
`data/acceptance/agent-code-workspace-20261022/`.

Normal production Auto CSV acceptance now passed without mocks: installed local
27B IQ2_XS, actual 131072 context, real offline Python, full six-row total 150,
unchanged source and CSV download, no repair. Its QA agent is paused and its model
unloaded. The earlier failure remains in history. See
`data/acceptance/data-agent-input-contract-20261022/production-smoke-result.json`.

Continue `feat/agent-site-preview` in `.tools/agent-site-preview`, following
[interactive preview](../agent-site-preview.md). Internal renderer/protocol and an
optional derivative image are implemented: 53 focused normal tests and one real
offline Chromium/container test pass (modules, click, literal text, PNG, replay,
stale rejection, blocked network/POST, reset and cleanup). No native/API preview
capability is registered or deployed. Full regression, owned Runner lifecycle,
archive broker, action receipts, resource admission, ordinary Run/API wiring,
agent UI and real website-agent acceptance remain. Do not advertise the direct
renderer test as an integrated preview. Image `ai-station-site-preview:development`
was built entirely from the existing local `ai-station-browser:local` base.

The preview uses an independent operator inspection Task with source project/build
provenance, not an autonomous agent execution; do not drop project tags to bypass
busy guards. Audit project busy checks to admit only this immutable artifact
viewer concurrently with coding. Reuse `browser_runs`/`browser_job`, private Runner
transport, owned process/container checks, RAM locks and build-archive validation.
Native resource broker serves only frozen archive entries to the synthetic
internal origin; generated JS must never execute in the authenticated UI origin.
The original checkout WIP stays untouched. Broader platform work remains active.

After CSV QA cleanup the operator loaded a separate owned model. Do not assume
GPUs are empty: instance `4554b9cd-50af-47e9-9f94-50ab9667888e` was ready at the
latest inspection (actual context 46080, user-triggered load at 08:34 UTC). The
#336 deployment preserved its exact container/context against the pre-deploy
backup; evidence `agent-code-workspace-20261022/preserved-user-runtime.json`.
Keep that runtime while working on CPU preview. Future rollout/acceptance must
snapshot actual ready instances immediately before changes, rather than reuse
an empty snapshot from the earlier QA state.


### Native preview continuation (2026-10-22)

`feat/agent-site-preview` now also implements the native half: `site_preview_runs`
(requests, archive identity, one session/action admission, safe journals, frame and
receipt inspection, exact container cleanup and Close), `site_preview_job`
(offline archive broker/persistent renderer/mailbox), `site_preview_action_job`
(registered per-action proxy) and `site_preview_source` (bounded ZIP validation,
module MIME and document-only SPA fallback). ProcessManager inspection/cancel
supports both new executor types. Typed endpoints live under `/v1/runs/site-preview`
and `/v1/runs/site-preview-action`; image capability is `/v1/site-preview/capabilities`.
The optional image requires protocol 2, now built as
`ai-station-site-preview:development`. Production `.env` remains unchanged, so the
new native capability is disabled there and the existing live release is intact.

Final real Native/renderer tests passed (2); focused fake/native/legacy tests also
passed, with the exact current count in `native-qualification.log`. The final
protocol root-path regression is retained once in the parameterized cases. Full
`./scripts/check.sh` on the final combined feature is still required. Do not merge
or deploy the unfinished control-plane/UI adapter. Preserve the operator's ready
Q4 model (instance documented above); this work requires no GPU.

Next implement `backend/app/site_preview.py`: freeze only successful same-Task
`coding_build` artifacts from project_validation, preserve source project/Run/Task
identity, operator preview Task plus ordinary action Runs, explicit filesystem_read
and browser_preview permissions, RAM/exclusive admission, early and final PNG
adoption, inspectable Close/reconciliation and truthful expiry/interruption.
`NativeJobExecutor` needs a default no-op polling observer for continuous frames;
resource-aware preview rejection must retain locks unless the new native Close
endpoint confirms cleanup. Native image/frame paths are derived UUID/revision
paths; use the existing `read_owned_file` verifier with an explicit 8 MiB bound
before immutable Artifact adoption. The native Close endpoint handles a request
journal even when a dispatch lost its registered process; unknown Docker creation
stays inspection-required.

Audit project busy checks for the immutable operator viewer: keep real project
tags and permit code/follow-ups concurrently only for site preview/action work.
Do not weaken write-work exclusion. Preserve legacy Coding APIs and reuse its
build-download component to host Preview. Canvas interaction must scale pointer
coordinates to the captured viewport and use exact frame revisions; input is
literal text/enum keys, no client-executed generated HTML/JS. Show build version,
CPU target, loading/blocked/expired/interrupted states and an explicit Close.
Full fake API/worker/resource/recovery plus real native/browser acceptance precedes
review/merge/rollout; the broader product goal remains active.

### Frozen native qualification and control-plane workspace

The native implementation is frozen at `dc373f585db01fbe2165fc0ebf59063dbb0e4328`
in `.tools/agent-site-preview`. Full `./scripts/check.sh` is running in the owned
user unit `ai-station-site-preview-native-check-20261022.service`. Inspect its
actual MainPID/state and `data/acceptance/agent-site-preview-20261022/full-check.log`
before taking action; `full-check-result.json` appears only at terminal completion.
Do not edit/switch that worktree while qualification runs. The controller verifies
both its head and tracked source remain unchanged. Final protocol-2 direct Native
and renderer acceptance already passed (2); the image is local and CPU-only.

Continue application integration in `.tools/agent-site-preview-workspace` on
`feat/agent-site-preview-workspace`, based on the frozen native head. Its initial
`backend/app/site_preview.py` provides strict Open/action DTOs, source provenance
freeze and viewport validation. `backend/tests/test_site_preview.py` passed 17
cases using the real build Artifact producer and a temporary database; no browser,
model or worker runs. The module is deliberately not registered in API/executors,
and has no execution handlers yet. Finish its API/worker/artifact/resource/Close
contracts and UI before advertising preview. The inherited native worktree must
stay frozen until its check finishes; later integrate the workspace branch back
into `feat/agent-site-preview` by fast-forward/merge and qualify the final combined
head before review/merge/deployment.

Important integration details: ordinary previews/actions use a separate operator
Task (no agent_id) but retain project/source build provenance. Add an explicit
read-only viewer predicate to project mutation busy guards; do not drop project
tags. Resource deferral must honor cooldown for this CPU executor (the current
GPU-ready condition exempts gpu=none); preserve the semantics for existing jobs.
A default no-op NativeJobExecutor polling observer may adopt live frames. Generic
resource-free native rejection is currently a terminal failure; preview rejection
needs an explicit Close/inspection path that releases RAM/exclusive locks only
after the new native Close endpoint confirms cleanup. Otherwise keep interruption
and inspection state. PNGs have derived revision paths, SHA/size, an 8 MiB bound,
and need immutable Artifact adoption plus exact action/frame lineage checks.
Do not execute generated HTML/JS in the station origin. Native source lookup for
SPA navigation distinguishes Document requests from missing API/asset resources.

### Preview integration follow-up — 2026-10-22

The active integration worktree is `.tools/agent-site-preview-workspace` on
`feat/agent-site-preview-workspace`, based on the frozen native preview head.
The native head qualified 1804 normal Python tests (seven opt-in skips). The
combined control-plane increment adds source-bound inspection Tasks, resource
admission, frame Artifacts, typed interactions and separate Close/reconciliation
Runs, an isolated preview page linked from successful builds, and conservative
recovery. A real CPU-only API/worker/Unix-socket/Chromium test passed.

A first combined collection found colliding backend/native pytest basenames;
backend tests are now `test_site_preview_provenance.py`,
`test_site_preview_execution.py` and `test_site_preview_worker_real.py`.
The full combined regression runs under the user service
`ai-station-preview-workspace-check2-20261022.service`; check its actual state and
`data/acceptance/agent-site-preview-20261022/workspace-full-check-result.json`
before restarting or claiming it passed. The operator's separate Q4 model is not
part of acceptance and must remain loaded. Full source review, UI/browser gates,
image/Compose verification and PR/deployment are still pending.

Preview integration continuation: draft PR **#337** targets `develop` from
`feat/agent-site-preview-workspace`. Real browser acceptance passed at 1440/390:
actual worker/socket/Chromium pointer, reload and Close, no GPU/model changes.
Frontend final checks on `5ae3263` passed 521 tests, lint/types/build, both Compose
configs and image build. A subsequent focused UI fix returns agent builds to
`/agents/<id>?view=workspace` instead of the legacy Coding route and adds a
regression test; qualify that updated head before release. The combined Python
service above remains the authoritative running check; its result JSON may still
contain the older collection failure until the current live process finishes.
Do not interpret that stale result file as termination or restart a live check.
No preview feature has been deployed yet; production remains PR #336.

Website-policy scope fix: the broad website recognizer incorrectly classified an
agent that merely reads CSV from a website as a builder. Creation verbs now bind
to the site; 34 focused factory/page-coding tests pass. The preliminary full check
is intentionally superseded because backend source changed. The authoritative
final full run is `ai-station-agent-website-policy-final-20261022.service`;
`workspace-full-check-result.json` must show exit zero and unchanged source.
The previous UI head `104a4a9` passed 526 tests and all UI/Compose/image gates;
frontend sources are unchanged by the factory fix, but the final image must be
rebuilt with the new backend before merge/deployment. PR #338 remains draft.

Website-policy final qualification: corrected source `9e6bc63` passed 1844 Python
tests/eight opt-in skips and Ruff, with unchanged-source proof. UI source `104a4a9`
passed 526 tests plus format/lint/types/build, Compose and image. Subsequent code
changes were backend-only; the final image and compiled assets were verified
against `9e6bc63`, and final actual desktop/mobile factory/save/reload passed.
Current release qualification requires full PR review and successful guarded
0028 rollout; the deployment manifest is authoritative. Current native source is
byte-identical to PR #337. Full real-model website execution remains separate
acceptance, and the operator-selected model must be preserved during deployment.

## Added backlog requirement: ordinary Chat page reading (2026-10-22)

Track [Chat page reading](chat-page-reading.md) in product completion. The operator
reported that asking Local AI to analyze `akademia.ai` for a promotional-image
prompt returned unrelated search snippets and hypothetical branding. Reuse the
existing public-page fetch/browser boundaries for ordinary Chat; recognize explicit
URLs/bare domains, honor Web, record sources, and test the exact request. This
requirement is planned; adding this record does not implement or qualify it.
