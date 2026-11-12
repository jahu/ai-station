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
