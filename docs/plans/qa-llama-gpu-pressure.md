# Respect observed GPU occupancy before llama.cpp startup

Real DATA-001 Auto analysis chose a qualified model from total VRAM while an
external runtime occupied a selected GPU. AI Station's own resource locks did
not represent that external allocation, so native startup failed with CUDA OOM.

Keep the existing hardware-fit/context proof and one-heavy-job-per-GPU policy.
Before dispatching a new GPU model, honor fresh native free/total VRAM (or total minus reported used memory): substantial
observed occupancy keeps the same durable load queued, with an inspectable GPU
wait and short retry delay. The initial conservative threshold is 90% free on
each selected GPU; this preserves the exclusive-heavy-job policy rather than
guessing that leftover memory will fit. Existing locks still arbitrate AI Station work;
only owned idle models may be evicted. Never signal external workloads, silently
spill to CPU, reduce a verified requested context or poison context-fit history
for temporary resource pressure. Legacy runners without memory observations
retain their existing lock-based admission and native startup verification.
CPU-only loads are unaffected. Stop, deadlines, dependency/recovery and sharing
continue through the existing Task/Run contracts.

A later successful Vision/F16 load must not erase an unchanged file's verified
Q8 coding history. A legacy/F16 instance without duplicate file metadata can
bind its actual successful owned load's source path, size, mtime, instance and
GPU set; neither declared trained context nor unrelated load events prove a
usable context. Auto still requires an installed, observed 100k+ local profile.

Qualify GPU occupancy/clearance, partial device pressure, sparse IDs, CPU and
legacy observations, waiting fairness, cancel/restart safety, independent work
and exact source proofs with fake native calls. Then use an isolated owned
bounded CUDA allocation to reproduce external-style pressure without touching
existing external services, and repeat the actual CSV case through the UI.
The separate busy-short-context upgrade refusal is not closed by this change.
