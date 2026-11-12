# Qwen reference noise replay

The same-day successful manual edits are a valid positive control: Qwen Image
2.1 performs substantial edits using the same checkpoint/encoders/VAE and legacy
engine as the failed reference-series case. A general Qwen failure was not proved.

The failed source and edit both use CUDA noise seed 42 at the same dimensions.
The native pipeline never forwards its Qwen seed to sd-cli, whose default is 42;
Edit/Recompose do not expose a pipeline seed argument at all. This also means
that explicitly requested seeds can be silently ignored. The successful manual
reference was produced with another model and does not replay Qwen's source noise.

Upstream reproduced this precise oversharpened near-copy behavior and isolated
replaying the source's initial noise, rather than CFG, model weights or a general
engine defect: [sd.cpp issue 2131](https://github.com/leejet/stable-diffusion.cpp/issues/2131).
This is a hypothesis for our case until a same-input/brief/engine/settings render
with only a different seed has been inspected.

Implementation: freeze a fresh bounded seed on each new automatic Qwen Run;
avoid the legacy default and known source seeds. Preserve explicit seeds and
saved retry identity. Forward the frozen seed to the real sd-cli for Generate,
Edit and Recompose through the owned pipeline import adapter, without changing
the external script or adding arbitrary executable options. Managed checkpoints
reuse their existing typed seed contract. Voice seed continuity is unrelated and
must remain unchanged. Preserve models, prompts, references, permissions, process
ownership, Stop and recovery.

Verify exact real argv with a fake executable, invalid/injected seed rejection,
explicit zero, model/profile/runtime combinations, stored automatic seed and
retry reuse. Qualify the original bad case by changing only its actual seed,
inspect pixels, then repeat the ordinary explicitly selected Qwen conversation.
Never substitute Krea or claim deterministic visual adherence from Run success.

## Controlled real result

The same bad source and instruction were rendered through an ordinary owner-scoped
Qwen Recompose Run with only the effective seed changed from 42 to 43. The engine,
checkpoint/companions, 832×1216 output, 30 steps and CFG 1 match the earlier engine
comparison. The resulting PNG independently records seed 43. Visual inspection
finds the severe sharpening/grain absent. The requested viewpoint change remains
conservative; the old instruction also asks to preserve posture. This confirms
the texture diagnosis, not full view-change acceptance. The subsequent ordinary
conversation explicitly requests Qwen and two independent results for inspection.

That conversation completed all 14 Runs with two distinct Qwen files, different
saved seeds, the same original parent and no rejected decisions. The first file
is a clean, substantially changed side view. The second is a clean rear/high view
but relocates a distinguishing source feature onto the back. This is not full
identity acceptance and is not caused by seed replay. Tighten generic planning
guidance: discretionary views should expose required preserved features, and
those features must retain their physical location rather than being moved or
duplicated to solve occlusion. Explicit requested views/changes remain
authoritative. No subject, camera list, keyword router or pixel crop is added.
Repeat the ordinary request after this guidance; inspect actual files again.

The reviewed application source passes all 2922 relevant backend and complete
Host Runner tests, with eight explicit opt-in/platform skips, plus repository
Ruff lint/format and a production Docker build. Coverage includes an actual fake
sd-cli process observing seeds for all three operations and both configured and
legacy engines, including zero and the uint32 maximum; invalid values fail.
Persisted automatic seeds, source collision avoidance, follow-up inheritance and
retry seed reuse are checked. The first local failures were a missing test import
and old stdout/parser expectations after wrapping; those were corrected before
the successful complete relevant-family run. No test failure is waived.
