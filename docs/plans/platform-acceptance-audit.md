# Platform release acceptance audit

In progress, 2026-10-25. This is an evidence map and remaining-work list, not a
claim of 100% completion. Preserve the original specification together with the
explicit agent-first and single-conversation decisions. Do not substitute one
feature PR, an available runtime badge or fixture output for full acceptance.

## Audited baseline identity (PR #445)

The shared deployment receipt below determines the current release after later
fixes. These exact identities describe the baseline audited here.

- Develop: `c5d48d94ae206d7722299baf8a538cddb706dec4`, squash merge of PR #445.
- Deployed reviewed source: `fefdf3c9e2cd4760f6689b497a0a872aacc68563`.
  Its Git tree is identical to that develop commit.
- Image: `sha256:85345426a71099a225213cc53eeb326fecd78db655b66c42d4d2efc03161042b`.
- UI: `http://192.168.1.121:8765`, also `http://127.0.0.1:8765`.
- Authority: `data/acceptance/safety-redeploy-20261012/deployment.json`.
  Current qualification and preservation receipts:
  `data/acceptance/unified-natural-agent-intent-20261025/`.

Fresh complete Python/Runner qualification is 4,123 cases: 4,114 passed and nine
opt-in integrations skipped. The whole frontend tree matches PR #444's successful
five gates and 844 tests. Exact image/backend/assets, normal/dev/private-LAN
Compose, isolated API/worker/SQL/SSE and compiled 1440/390 workflows passed.
Those browser workflows use fake inference and owned CPU image fixtures; they
are not new real model/GPU acceptance. Both rollouts retained original row IDs,
auth settings, E5 vectors, native/private services and owned model instances.

## MVP evidence map

| Requirement | Evidence inspected | What it proves; remaining verification |
| --- | --- | --- |
| MVP-111: startup | PR #445 deployment and verification receipts; owned `scripts/start.sh --no-build` launch | Current API, three worker slots, scheduler and private Runner are live. General bootstrap/prerequisite coverage remains in the existing normal suite and historical startup acceptance. |
| MVP-112: dashboard | Current native hardware observation in PR #444 evidence; current deployment health | Two actual GPUs and temperatures were observed; this is telemetry/readiness, not a fresh GPU generation or sustained-load benchmark. Reconcile the final Home/System QA cases against the actual release. |
| MVP-113: Chat | Current browser/normal qualification; earlier real provider/streaming evidence in the product ledger | One conversation, ordinary reply, model controls, persistence, tools and Stop. PR #445 also proves polite creation with default Web does not search its goal. Retain earlier real inference scope separately. |
| MVP-114: Images | `krea2-lustify-20261025/milestone-complete.json`; prior six photo-pipeline smoke cases | Real Krea Generate/Edit/one+two-reference Recompose and Stop at recorded GPU-only profiles; original script preserved. New translation/recovery composition is separately qualified. No universal visual-quality claim. |
| MVP-115: Runs | Current complete suite, image smoke and deployment preservation | Durable lifecycle, events, atomic claims, leases, conservative recovery, Stop, artifacts and retained history. Extended concurrent-use acceptance must be reconciled with recorded stress profiles. |
| MVP-116: Projects | Existing managed-project/worktree tests and real website receipt | Name-only managed setup and isolated workspaces, with original checkout preservation. Existing repository registration and advanced policies remain available. |
| MVP-117: Coding | `agent-website-real-20261022/result.json`; local-code/data receipts | Actual local-model website creation, preview, build and same-workspace follow-up passed at 131072 context. This is a concrete scenario, not arbitrary website fidelity. Standalone IDE/Cursor/Codex expansion is explicitly deferred by the user. |
| MVP-118: self-development | Historical documentation-only Cursor receipt and current development workflow | Preserve the tested foundation; full self-development is no longer a required product milestone under the agent-first decision. Do not claim broader real external-agent acceptance. |
| MVP-119: Agent Factory | Current complete suite and compiled desktop/phone drafts | Natural Polish/English creation, exact selected-input/completed-analysis source binding, disabled definitions and explicit activation contracts. Broader real-model factory compositions still need a finite final sweep. |
| MVP-120: Agents | Actual website/data reports and scheduled-agent receipts in the product ledger | Real local code/data and concrete recurring observations are established. Reconcile current multi-tool/notification cases; external mailbox delivery is not proved by private SMTP tests. |
| MVP-121: Memory | `managed-memory-release-20261025/activation-result.json`; real-model and deployment preservation receipts | Actual pinned Multilingual E5 Small INT8 CPU embeddings, 384 dimensions and all three existing entries indexed. Scoped/disabled retrieval and persistence have separate real/normal checks. |
| MVP-122: Models | Existing real 27B/long-context receipts; current read-only runtime observations | Actual 131072-context local execution is recorded. Available/configured metadata alone is not fit verification for every installed model or profile. |
| MVP-123: Diagnostics | Current native readiness and deployment observations | Actual private Runner, GPU detection and configured media capabilities are observed. Preserve available/unavailable/misconfigured distinctions; reconcile complete diagnostics against the final catalog. |

Receipt paths in this table are below `data/acceptance/`. Historical receipts
remain scoped to their original model, parameters, source and runtime. Normal
regressions of newer source do not relabel an old integration as a fresh real
execution. The operator case catalog is v11 with 158 stable IDs in 21 areas. All
158 are mapped to source, current regression and concrete historical receipt
scopes in [the internal coverage review](../qa/internal-coverage.md). That review
retains unverified cases rather than marking them passed.

## Corrections to stale evidence interpretation

The website build-policy document's earlier pending real scenario was subsequently
completed: `agent-website-real-20261022/result.json` records real local inference,
normal workers/Runner, unmocked Auto loading, two builds and a preview/follow-up.

`python-data-agents-20261022/production-smoke-result.json` is **false** and must
not be counted as a pass. The later
`data-agent-input-contract-20261022/production-smoke-result.json` passed with
normal workers/Runner, unmocked loading, preserved synthetic input and total 150.
The separate earlier CSV/XLSX total-27 receipts freeze an already-loaded runtime;
they do not establish Auto loading. Keep these distinctions in the final report.

## Remaining release work

1. The actual goal-prepared video-agent gap is now qualified in
   `agent-video-release-20261025/result.json`, `visual-review.json` and
   `real-player-result.json`: actual natural 9B draft, goal preparation, two Wan
   windows, full five-second film and compiled playback. A real factory-schema
   defect was fixed in PR #447; the earlier false receipt remains unchanged.
   The tested profile explicitly reviewed a 7200-second maximum. PR #448 qualifies
   fresh disabled-draft defaults separately: actual 9B null becomes a visible
   controller suggestion, while an explicit five-minute limit remains 300.
   Public settings, saved/running and explicit numeric budgets stay unchanged.
   Its deployment receipt determines whether the correction is live.
2. Reconcile Video/Avatar duration and quality claims with exact recorded profiles:
   earlier real 60-second Wan draft and 30-second avatar do not prove every longer
   or higher-quality profile. The actual four-window ten-second Wan test at
   20 steps passes decode/assembly/playback but fails visual quality with
   progressive whitening. A read-only VAE probe identifies a temporal boundary
   mismatch in raw-tail reuse; diffusion comparison remains in progress. Follow
   [the continuation investigation](wan-continuation-quality.md), preserving the
   failed visual receipt. Current capability checks start no inference.
3. Keep external-account acceptance explicit. The owned Tailscale helper currently
   reports `NeedsLogin`, not serving: worldwide mobile acceptance is unperformed.
   SMTP private-sink qualification is not real operator-inbox delivery. These
   require owner-controlled setup and, for a real message, concrete send approval;
   never request passwords/tokens in chat or manufacture successful receipts.
4. Generate the actual release-specific Polish QA package after internal readiness:
   six-sheet XLSX, CSV feedback/retest templates, instructions, manifest and
   accurate qualified profiles/test prerequisites. All operator results start
   **Nie testowano**. A catalog or a draft export is not this final handoff.
   The offline exporter now includes synthetic CSV/two-sheet XLSX/document/PNG
   inputs, an intentionally invalid input and checked values/hashes. Its eight
   offline checks pass; neither those inputs nor a draft export prove inference.
5. Keep the full-platform goal open until the applicable requirements and required
   handoff artifacts are proved; do not count deferred/future or unverified work
   as completed. Preserve unrelated root Memory WIP and existing operator data.
