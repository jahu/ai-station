# Avatar quality: evaluate the model before promoting another recipe

2026-10-28, following the operator's negative AVATAR-005 review. QA-020 remains
open: facial appearance, especially the eyes, changes over the full recording.
Technical completion and the earlier color improvement do not satisfy visual
acceptance. Keep the original adverse output and first-pass QA history.

## Established observations

The current EchoMimic Flash profile is 384-square, eight steps and
`portrait_anchor_v1`. It already anchors continuation windows to the original
portrait while preserving raw temporal history. Earlier controlled trials of
lower audio guidance, pixel-only prefixes, independent portrait resets and fixed
recoloring did not satisfy both appearance and continuity. Do not repeat them as
new fixes. The installed upstream `run_flash.sh` itself selects eight steps;
raising a distilled model's step count is an experiment, not a quality guarantee.
See [the retained investigation](echo-continuation-quality.md).

The machine used for the present evaluation has two separate 12-GiB RTX 3060s
and about 32 GiB of host RAM. This is an observed test configuration, never an
application requirement. Device memory does not automatically combine into a
single 24-GiB allocation. A candidate must prove its actual memory behavior.

## Candidate decision

| Candidate | Evidence and decision |
| --- | --- |
| EchoMimic Flash | Keep as the unchanged control. Current long-recording visual acceptance failed; successful decoding is not a fix. |
| InfiniteTalk 14B | First comparison candidate: supports portrait/audio input and long continuation with head/body/expression motion. Evaluate INT8 and bounded offload before offering a runtime. Quality and fit on this workstation are unproved. |
| MultiTalk | Related fallback; its own documentation describes long-video color accumulation and APG. It is not presumed immune to drift. |
| MuseTalk 1.5 | Useful separate lip-sync candidate with a documented low-memory example. Lip-region inpainting is not equivalent to a fully animated portrait; a static head is not a substitute for passing AVATAR-005. |
| LatentSync | The official requirements distinguish 8-GB v1.5 from 18-GB v1.6. It is a lip-sync option, not a verified 12-GB full-avatar replacement. |
| Sonic | The authors report testing on a single 32-GB GPU. That is neither a proved minimum nor evidence of fit on two 12-GB cards; defer pending a bounded compatible implementation. |

Sources inspected on 2026-10-28:
[EchoMimic](https://github.com/antgroup/echomimic_v3),
[InfiniteTalk](https://github.com/MeiGen-AI/InfiniteTalk),
[MultiTalk](https://github.com/MeiGen-AI/MultiTalk),
[MuseTalk](https://github.com/TMElyralab/MuseTalk),
[LatentSync](https://github.com/bytedance/LatentSync),
[Sonic](https://github.com/jixiaozhong/Sonic).
These are upstream claims, not AI Station benchmarks.

## Reproducible first experiment

Use a separate project-owned cache and virtual environment. Pin and hash the
source and every required weight, tokenizer and encoder. The inspected WanGP
revision `7b2cafb7f923dde005f0933d75bca3f651a13d4e` includes InfiniteTalk and
INT8/SDPA support without the current installation guide's CUDA-13 environment
instructions. It is an evaluation implementation, not a production dependency.
Do not execute its general UI startup/download path: inspection shows unrelated
asset downloads, file migrations and removals. Build a fixed offline entry around
only the required pipeline, with no public server, enhancer, agents or cloud tools.
The inspected WanGP snapshot declares a non-commercial evaluation license.
Record that separately from the model/encoder licenses; no redistribution or
commercial compatibility is established by this experiment.

Use the same neutral synthetic adult portrait, complete canonical QA recording,
frame rate and source hashes as the retained failure. First collect a bounded
short output to prove loading, meaningful motion and correct speech duration;
this cannot pass the long-recording case. Then render the complete same recording
and inspect the beginning, middle, end and all continuation joins. Compare eyes,
face proportions, color, head motion, seam jumps and lip-sync with the source and
control. Do not conceal drift with frozen frames, cosmetic face replacement,
loops, silent padding or a shorter final acceptance clip.

Set a kernel-enforced host-memory/swap bound, explicit time limit, one selected
discovered GPU, and owned process-group cleanup. Measure RSS, peak VRAM, full
elapsed time and source/model/implementation hashes. Yield to active operator
work. An idle AI Station-managed model may be temporarily stopped through the
normal typed API only after saving its exact profile; a finally controller
restores that profile unless new operator work or another model choice intervenes.
Never stop an external runtime. Model files, existing installations, drivers and
CUDA remain unchanged. A failed fit is useful evidence;
never relax ownership, memory or filesystem boundaries to obtain a green result.

## Promotion and public workflow

Only promote a candidate after the complete comparison improves the reported eye
and identity defect without an unacceptable motion/seam regression. Before then,
keep it unavailable in diagnostics and selectors; downloads alone do not establish
availability. Retain failed outputs and negative measurements.

An accepted engine uses the existing Task → Run → Events → Artifacts path,
typed native Runner operation and discovered resource admission. Freeze engine,
model and recipe observations at enqueue; preserve legacy jobs and exact resume
identities. Test permissions, source/path/hash validation, Stop, recovery,
resource release, result lineage and unsupported configuration with fakes. Then
qualify actual manual and agent/browser workflows, ordinary Library playback and
the full recording before changing the recommendation. Keep the UI's portrait,
speech and understandable quality choice; do not add technical mode switches.

## Current acceptance state

The owner-reported eye deformation is a failed QA case, not an unavailable-device
case. The owner subsequently confirmed all seven phone/network cases; these are
human-reported passes, not AI browser emulation. The current frozen QA catalog has
158 passes, one avatar-quality failure, no blocked cases and two SMTP cases marked
not applicable. The first-pass results and failed retests are preserved.
The initial 19 fixed issues remain confirmed successes. This report does not infer
an audio-quality verdict from phone acceptance. QA-020 requires a real visual
retest; no alternative engine has yet passed the complete comparison.

## Measured InfiniteTalk technical probe — 2026-10-28

The pinned WanGP implementation above loaded verified INT8 weights and completed
one **81-frame, 384×384, 25-fps** window with **four** denoising steps. Measured
wall time was **445.64 seconds for 3.24 seconds of output**, with a Torch allocated
VRAM peak of **6,461,834,752 bytes** on one RTX 3060 12 GB. The worker was bounded
by an 18-GiB host-memory cgroup, no swap and a 600-second deadline. This is the
measured profile, not a general speed claim for InfiniteTalk or every offload
configuration. A preceding constrained-memory attempt hit its real deadline;
failed attempts are retained.

The benchmark temporarily stopped one idle **Station-managed** llama.cpp instance
through the ordinary API. Its exact original two-GPU, 131072-context, Q8-cache
profile was restored and verified ready afterward. No external runtime was
stopped, and no existing environment was upgraded.

The clip is a **technical probe, not a quality acceptance**: four steps are below
the non-accelerated reference setting, the clip is short, and early frames already
show color/detail changes. Do not infer that a full-quality model is good or bad
from this reduced-step output. Do not dispatch an hours-long comparison blindly
from this result. The native experiment was imported into the private Library as
a clearly labeled diagnostic without inventing a normal application Run; browser
playback and downloaded bytes were verified. It is not published with repository
media.

Private local receipts: `infinitetalk-short-smoke-result.json`,
`infinitetalk-exclusive-model-restore.json`, and
`infinitetalk-library-browser-proof.json` under
`data/acceptance/browser-qa-20261026/`. The current production engine/defaults
remain unchanged.

## Sonic staged evaluation

Sonic source is pinned to `c1bd2d133ecc72f1a5abd990f1de101efcc3cfdb`.
Public source weights and supporting SVD/Whisper files were downloaded into a
separate evaluation cache and hash-verified. A CPU-only load verified all 1492
trained UNet state keys with `strict=True`, no missing/unexpected keys and no meta
parameters. Consequently the redundant base SVD UNet weights are not required:
the complete trained checkpoint is loaded into the same configured architecture,
including its audio adapters. This verifies loading, not numerical equivalence
of different precision/offload strategies or generated quality.

The unchanged full source recording produced 1002 input audio frames and a
768×512 portrait/mask. Its complete 40.08 seconds remain the eventual acceptance
input. A bounded short generation at the native 25-step setting precedes that
comparison. No Sonic runtime is offered in production, and CPU preprocessing alone
is not evidence of GPU fit, complete output or stable facial motion. The inspected
source license is CC-BY-NC-SA 4.0; model/component terms remain separate and no
commercial redistribution compatibility is established here.
