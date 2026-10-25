# Owned Python recovery acceptance

The remaining reliability work needs evidence beyond injected process responses.
Add an explicit opt-in command that creates a disposable repository, migrated
database and private native Runner, and uses the already installed trusted Python
container image. Do not build/download images, use inference, change the live
deployment or read its credentials. Native launch and inspection use typed HTTP
over the private Unix socket; enqueue/claim/heartbeat/recovery use normal services.

Launch one ordinary Python Run, wait for its owned CPU container to run, and kill
only the test worker process. After its actual lease expires, recovery must inspect
the live process without dispatching it again. When that process completes, mark
the uncertain Run interrupted for inspection rather than inventing success or
adopting outputs. A second case requests cancellation after the worker crash;
recovery must stop that exact owned process/container and finish canceled. Neither
case may publish successful Library outputs or repeat execution.

Record actual lifecycle events, container ownership/removal and original fixture
bytes. Cleanup signals only test-created processes and uses typed per-Run cancel
for any remaining owned jobs. Keep failure evidence and refuse to remove a
workspace whose owned container cleanup is uncertain. This command qualifies the
recorded CPU failure/recovery path, not every adapter or sustained GPU concurrency.
Normal tests remain CPU-only and never launch Docker workloads unexpectedly.

Actual acceptance on 2026-10-25 passed both cases using installed image
`sha256:5411ba6468552ae9c08fc5b51f1e9583546ec3059daf6ddecf7dca989e516bf5`.
The final probe additionally verifies the same native PID and exactly one script
start, completion/cleanup flags and absence of owned Docker containers. Both
workers were actually killed; leases expired naturally. Original repository/index
and script bytes were preserved, and no successful output was published. The
completion case became interrupted; the cancellation case became canceled.
`data/acceptance/owned-python-worker-recovery-20261025/actual-final/result.json`
records the cases. An earlier invalid image-ID configuration failed availability
before any workload; its evidence is retained. The command now rejects that form
before launching and accepts only the native executor's installed tag namespace.
Ruff/check/format and the explicit opt-in guard pass. Production Python/Runner,
frontend and Docker inputs are unchanged; exact-source reuse of #428's complete
local gates is recorded with the reviewed head rather than repeating GPU or UI
work for this acceptance-only command. Native restart and sustained concurrent
work remain separate acceptance; this does not close the whole-platform goal.
