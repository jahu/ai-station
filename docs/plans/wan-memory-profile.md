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

## Bounded qualification preparation

Installed Comfy casting code selects manual conversion when native FP8 compute
is unsupported; the candidate uses `fp8_e4m3fn`, never the accelerated option.
A disposable 128 MiB user service reported the actual memory/swap bounds, and a
separate 64 MiB allocation probe was killed with kernel/unit `Result=oom-kill`.
That proves isolation, not a usable large-model peak (systemd's post-exit peak
property was too small to trust; record live cgroup samples instead).

Candidate commit 32c6b0d accepts the fixed private engineering loader option;
public/native Video requests and capabilities still expose only the working
default. 27 focused cases passed, including rejection before Comfy imports. The
opt-in `qualify-fp8.py` evidence helper prepares one 512×288/17-frame/four-step case
under an 11 GiB memory cap, zero swap and 600-second runtime. A wrapper verifies
kernel limits before model import. During this engineering probe only, the
project's worker/scheduler are paused after owned-LLM stop. The exact preset
reload is queued durably before launch; the owned unit's stop hook restarts only
those inspected containers, including if the observer disappears. The API,
Host Runner and unrelated services stay running. Finally also verifies restoration.
No result or product availability may be claimed until actual execution, peak,
full decode, inspected frames and restored operator state are recorded.
