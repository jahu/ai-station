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
work; do not stop another runtime merely to benchmark. Existing models,
installations, drivers and CUDA remain unchanged. A failed fit is useful evidence;
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
case. Seven separate physical-device/network cases remain unverified; this report
neither passes them nor infers an audio-quality verdict. The initial 19 fixed
issues remain historical successes. The new open issue requires a real visual
retest; no alternative engine has yet passed one on this workstation.
