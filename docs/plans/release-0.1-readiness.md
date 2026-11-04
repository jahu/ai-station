# Release 0.1 readiness — 2026-11-04

The owner's priority is a reliable first experience on **Linux and Windows**.
This audit follows [the accepted scope](next-release-0.1.md). macOS and SMTP
are deferred; future nodes and large standalone IDE work are not release gates.
The release is **not complete or publicly published**.

## Frozen candidate

Reviewed PRs [#629](https://github.com/jahu/ai-station/pull/629) and
[#630](https://github.com/jahu/ai-station/pull/630) are merged into `develop`.
Runtime source: `4a1d8281f8ba5bdbc93b6b40a0956773e23e37b1`.

| Private artifact | SHA-256 |
| --- | --- |
| `AI-Station-0.1.0-linux-amd64.deb` | `240704a07bb408da40cb98c55720996a070e12882c8d9f42e3cc2971a176112f` |
| `AI-Station-0.1.0-windows-x64-Setup.exe` | `ecd3aa79c73d1b0a589bf1f696d37c9c85b951ee2f3b8b6ec9cb182af32d2490` |

The Windows EXE's measured ProductVersion is `0.1.0` and signature status is
**NotSigned**. These names/checksums identify private candidates, not download
links or approved public assets. Signing/rebuilding changes bytes and requires
new checksums. QA documentation may advance independently of this runtime source.

**Owner update, 2026-11-04:** physical Windows GPU tests and voice/film listening
will happen after release. Preserve them as untested post-release QA, not gates
to publication. The owner also explicitly approved unsigned Windows distribution
for 0.1, with signing deferred and warnings disclosed.

## Requirement audit

“Delivered” below means implemented and internally qualified at the recorded
profiles. It does not prefill operator answers, guarantee all model outputs, or
claim every hardware/vendor combination works.

| Requirement | Current result | Direct operator cases |
| --- | --- | --- |
| NR-01: persistent creative work | Delivered: saved history, sources, feedback, variants and restart for the five creative workspaces. | CREATIVE-101–105 |
| NR-02: progress and estimates | Delivered: durable whole-task stages and measured/indeterminate progress; insufficient timing data stays explicit. | PROGRESS-101–102 |
| NR-03: structural image editing | Delivered for recorded neutral Qwen fixtures; explicit LUSTIFY preserved. LUSTIFY's observed structural weaknesses remain recorded. | IMAGE-101–102 |
| NR-04: local prompt improvement | Delivered with actual local preparation → image result, frozen effective inputs, script/lyrics preservation and recovery contracts. | PROMPT-101–104 |
| NR-05: completed deletion cards | Delivered with persistent dismissal and retained Run history. | LIB-101 |
| NR-06: expressive speech | Functional delivery and real short/long/pace/Stop checks passed. Human emotion/fidelity listening is owner-planned post-release QA. | AUDIO-101, VOICE-001–005 |
| NR-07: synchronized effects | Real video → MMAudio → timeline/export and complete-file checks passed. Human sound/scene and multi-scene quality acceptance is owner-planned post-release QA. | AUDIO-102, CHAT-101–102 |
| NR-08: editor | Delivered: saved revisions, independent tracks, waveform/timing controls, preview/export and scoped Stop. | VIDEO-101–102 |
| NR-09: name | Owner approved AI Station / Your own AI. Made simple. | DOC-101 |
| NR-10: model freedom/responsibility | Delivered in README with format, license and legal boundaries. | DOC-102 |
| NR-11: private accounts | Delivered: migration/isolation, explicit admin inspection, remembered cookie sessions, TOTP/recovery, account controls and private caches. | ACCOUNT-101–107 |
| NR-12: prepared Web queries | Delivered: selected-model preparation, contextual follow-ups, visible queries, permission-bound search and direct page reading. | WEB-008–009 |
| NR-13: consumer installation | Linux clean CPU journey and Windows 11 private-WSL CPU journey, preserving update/Stop/restart passed. Unsigned distribution accepted; fresh physical GPU journeys remain unqualified. | INSTALL-101, SETUP-146–154, SETUP-159–164 |
| NR-14: hardware-aware setup | Guided conversation/media/memory profiles and verified download/recovery are delivered at recorded configurations. Physical Windows GPU first result is owner-planned post-release QA. | SETUP-101–145, SETUP-160–164 |

The v46 catalog contains **261 active cases**, retaining four deferred Mac
definitions separately. v45 added 24 cases to close explicit requirement coverage
gaps; v46 adds the physical Windows GPU journey for post-release QA. All previous
definitions/IDs remain intact. Existing v15 answers and
later draft workbooks are preserved. Catalog coverage is not test execution.

## Evidence that need not be repeated

- Python regression: **8,020 passed, 19 explicit skips**, four existing warnings.
  Final late publisher/root-file changes additionally passed 77 complete affected
  helper/probe/consent/bundle cases; stable version/update/package families
  passed 159 cases. No failing tests were waived.
- Ubuntu: native authentication/cancel, package-manager exclusion, exact fixed
  package preparation, root-only configuration/backup, controlled same-operation
  recovery and normal OS restart. The CPU-only fixture cannot demonstrate GPU
  inference. The separate real workstation passed the packaged two-device CUDA
  readiness query without a model load or host configuration change.
- Windows: actual native installer, first CPU reply, preserving installed-UI
  update, same account/history/model records, original browser cookie and
  conversation, native Start/Stop and normal OS restart. The final native files
  and compiled runtime match the previously qualified code; the final export
  was a build/identity check, not another inference run.
- Both disposable OS fixtures shut down normally. Superseded project build
  inputs were removed after final artifact verification. Production data,
  models, external services and the working host configuration were preserved.

Detailed contracts/observations: [desktop installation](desktop-installation.md),
[Linux graphics preparation](linux-gpu-onboarding.md),
[speech](expressive-speech.md), [sound/editor](synchronized-sound.md), and
[operator handoff](operator-qa-handoff.md). Local private receipts are retained;
no credentials, private Library media or operator answers belong in this document.

## Remaining release decisions and work

1. **Post-release physical Windows NVIDIA (owner):** install on real hardware, confirm detected GPU,
   obtain the recommended model's real first reply, Stop/reload and ordinary
   reboot recovery, preserving unrelated software. A CPU VM, mocked GPU result
   or Linux execution cannot satisfy this gate. Capture OS/driver/card/profile
   and installer identity, without secrets. Availability was requested from the
   owner. The owner now explicitly schedules this after publication (SETUP-164).
2. **Additional fresh Linux NVIDIA qualification:** qualify prepare → explicit ordinary OS restart
   → unprivileged readiness → first recommended GPU result on a separate suitable
   physical installation. Existing workstation readiness and clean CPU-VM
   preparation are useful independent evidence, not that combined journey.
   Do not alter the owner's working graphics/daemon setup to simulate a fresh PC.
   Advertise the actual independently qualified Linux paths above; this additional
   combined-hardware trial remains a documented coverage limit, not a claimed pass.
3. **Distribution accepted:** publish the unsigned Windows installer only after
   human-owned master promotion. State that SmartScreen can show an unknown
   publisher and Smart App Control/managed policies may block execution. Do not
   tell users to disable operating-system protections. A paid signature is future
   work; it would not guarantee immediate SmartScreen reputation.
4. **Post-release human media acceptance (owner):** listen to the retained eight neutral Fish samples
   and inspect the private film/sound auditions; record expression/completeness,
   sound correspondence and specific defects. Existing artifacts can be reused;
   do not regenerate expensive media to substitute for a listening decision.
5. **Final QA and promotion:** freeze accepted artifact hashes,
   generate/inspect/round-trip the final Polish workbook and fixtures, prepare
   release notes and the reviewed bot-authored PR to `master`. **Only @jahu may
   approve/merge master.** Publication/signing must retain the accepted source
   and artifacts. No new tag, public release or master merge has occurred here.

The complete future platform vision is broader than this release. Completion
claims must stay tied to this accepted scope and actual evidence, not an invented
overall percentage.
