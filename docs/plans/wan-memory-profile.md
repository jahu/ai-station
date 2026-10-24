# Qualify an optional Wan profile with lower memory use

Read-only inspection of the actual configured safetensors headers and installed
ComfyUI loader is retained in
`data/acceptance/media-memory-investigation-20261024`. The diffusion weights are
F16 (~10 GB); the text encoder already mixes F8/F16 (~6.7 GB). The current native
reservation is 15811 MiB plus 1024 MiB headroom, versus observed 12978 MiB available.
Idle owned-LLM eviction already exists. No generation, conversion, admission
change, download or external-runtime modification was performed in this inspection.

The installed UNETLoader exposes `fp8_e4m3fn`. That is an implementation candidate,
not proof of this GPU's support, memory fit, speed or visual quality. Preserve the
working default loader and old media receipts; do not lower their reservation.

1. Inspect the installed load/cast path and kernel fallbacks before selecting a
   supported fixed option. Reuse original read-only weights; no replacement model
   download or converted huge copy. Add only an explicit reviewed profile choice
   to the existing Video/agent schemas, frozen plan and typed native builder.
2. Bind precision/profile to the model-file observation, request identity,
   continuation checkpoint and output metadata. Legacy requests keep their exact
   default identity. Unsupported/unqualified profiles remain unavailable.
3. Prepare one opt-in engineering qualification using existing weights and a
   short bounded case. Prove transient user-service/cgroup memory and swap limits
   are available before launching it; enforce a finite runtime and owned cleanup.
   Require measured free capacity plus headroom, no other owned GPU consumers,
   and preserve/restore the operator's actual model preset. Never stop unrelated
   applications, alter OS/driver settings or repeatedly submit a known rejected
   normal media Run. A contained OOM is a failed profile, never a successful result.
4. Record peak memory/cgroup outcomes, full output decode, timing and inspected
   visual frames. Only a concrete passing profile can justify its own conservative
   dimension/frame-aware reservation. Do not extrapolate a tiny case to all
   dimensions, 81-frame chunks or a full film. Then qualify ordinary worker/agent
   execution and existing Stop/restart/lineage paths at that exact profile.
5. Expose the reviewed option with clear quality/resource wording and existing
   progress/results in Video and agent editors. Keep the original full-quality
   route. Complete normal tests, compiled desktop/phone checks, exact image/source
   review and coordinated release through develop.

The whole-platform goal remains active. This work is not authorization to bypass
RAM admission or claim real agent GPU success. Preserve prior long-media evidence,
root Memory WIP and pending Whisper-small download consent.
