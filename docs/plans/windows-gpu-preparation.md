# Windows NVIDIA preparation — NR-13/14

This extends the [Windows consumer installation](windows-consumer-installation.md),
not its completed private CPU qualification. Windows GPU inference is not yet
qualified. The existing Linux NVIDIA profiles and CPU-only Windows flow retain
their contracts.

## Observed gaps

The private guest installs Docker but does not install NVIDIA Container Toolkit.
All native NVIDIA queries previously required `nvidia-smi` on PATH. NVIDIA's
[WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html) documents the
projected `/usr/lib/wsl/lib/nvidia-smi` executable and limited NVML sensors. A
complete optional-sensor query can fail even when the device is present.

The discovery correction uses the existing PATH first, then that single fixed
Linux executable only under a Microsoft WSL kernel. No Windows drive search,
executable interop, package install or environment change is involved. Telemetry,
diagnostics, compute-process inspection and guided media driver/BF16 checks share
the same choice. Only WSL's unsuccessful combined sensor query gets one basic
device/memory query; absent sensors remain null. Missing executables, timeouts,
failed basic queries and ordinary Linux NVML failures never become successful
empty or invented hardware observations. This correction alone does not prepare
Docker GPU access or qualify a workload.

## Remaining implementation sequence

1. Include a reviewed, version/hash-pinned NVIDIA Container Toolkit package set
   in the application-owned guest. Use the publisher's signed stable metadata;
   retain package versions, hashes and licenses. Never install Linux display
   drivers or CUDA driver meta-packages. The physical Windows driver remains an
   OS prerequisite and is never changed by this work. The
   [official toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   identifies four packages and the required Docker registration.
2. Configure only the owned guest's Docker daemon. Preserve its ordinary runc
   default so a CPU-only installation stays usable. Do not modify Docker Desktop,
   another distro, the host, global `.wslconfig`, drive mounts or Windows interop.
   Runtime configuration can be [reloaded by Docker](https://docs.docker.com/reference/cli/dockerd/#configure-runtimes-using-daemonjson),
   but do not assume this registers a newly installed NVIDIA device driver.
   [Moby 27.5.1's NVIDIA integration](https://github.com/moby/moby/blob/v27.5.1/daemon/nvidia_linux.go)
   registers that driver at daemon initialization only when its hook is already
   on PATH. Inspect the packaged engine version and verify actual selected-device
   requests. A first-import image must install the hook before Docker starts.
   A preserving update must handle any necessary owned-daemon restart through
   the explicit idle-update lifecycle, retaining or safely stopping only verified
   owned workloads. A successful reload or runtime listing alone is insufficient.
3. Qualify a preserving upgrade for already-installed guests. The current updater
   deliberately rejects a changed guest Dockerfile/OS recipe. Merely changing
   the first-import image would leave existing users without the prerequisite.
   Add a fixed, identity-checked guest migration with interrupted/repeated update
   recovery, retained distro/data/account identity and no unregister/reimport.
   Do not remove that check or run an arbitrary package-manager command through
   the desktop/Runner interface.
4. Observe actual driver, devices, toolkit registration and selected-device
   container access before offering a GPU profile. Native detection alone must
   not imply container readiness. NVIDIA documents device-selection limitations
   for older Docker/WSL combinations; do not replace exact allocated device IDs
   with all devices to make a test pass. Verify the current installed combination
   and fail with an actionable message when its isolation contract is unsupported.
5. Run an actual Windows NVIDIA first-download/load/response or generation,
   bounded RAM/zero-swap, exact GPU selection, Stop, restart/recovery, preserving
   update and CPU regression. Exercise single- and multiple-device observations,
   unknown sensors, unavailable driver/toolkit and no-GPU startup. Keep existing
   private account, owned-container and immutable model/profile boundaries.

Normal tests use simulated CLI output and temporary files. The retained Windows
VM has no GPU passthrough; it can verify CPU/update behavior, not physical GPU
discovery or inference. No unsupported cross-platform completion claim follows
from those tests. NR-13/14 and the complete release goal remain open.

## Offline package inputs

`scripts/windows_gpu_bundle.py` prepares only four pinned amd64 toolkit packages
at version `1.20.1-1` (8,751,700 bytes). Their lengths and SHA-256 hashes were
checked against the publisher's Packages index, whose SHA-512 matches an
InRelease signature verified with NVIDIA's public signing key
`C95B321B61E88C1809C4F759DDCAE044F796ECB0`. The source identity is frozen in code;
preparation never selects a floating latest release. Package copyright files
retain Apache-2.0 and component notices inside the original Debian archives.

The developer builder uses fixed HTTPS sources without ambient proxies or
redirects, bounded transfers, complete verification before publication and a
fresh destination. A verified local bundle can be reused offline. Unexpected
files, shared-writable files, links, changed receipts/hashes and incomplete
transfers are rejected. Failed preparation removes only its own staging directory.

The Linux package builder's explicit `--windows-gpu` option includes these inputs
and the verifier in the immutable application inventory. `--gpu-cache` reuses
an existing verified bundle. Ordinary Linux packages omit them. Only an inspected
bundle earns the `X-AI-Station-WSL-GPU-Recipe` package field; the package has no
automatic install hook. Example developer build:

```bash
python scripts/windows_gpu_bundle.py --output /private/build/toolkit-inputs
python scripts/build_linux_package.py --output /private/build/windows-app \
  --deb --windows-gpu --gpu-cache /private/build/toolkit-inputs
```

Preparing inputs does not change any host package, driver, Docker daemon or model.

## Owned-guest activation candidate

The Windows guest builder now requires the explicit offline GPU package variant.
Its fixed image recipe installs the four verified packages while service startup
is disabled, validates Docker configuration and registers the NVIDIA runtime
before the first daemon start. The default runtime remains runc. A root-owned
receipt distinguishes image preparation from a verified real GPU workload.

Existing private guests use one explicit forward migration between the reviewed
CPU and GPU Dockerfile hashes. The base image, disabled drive/interop settings
and ordinary-user bridge remain exact; arbitrary OS/bridge changes and a reverse
migration are rejected by both native PowerShell and the Linux updater. The
updater holds its existing idle/database/desktop locks, verifies the new package
and runs only its fixed root-owned toolkit helper before publishing the target
guest identity. A failed or interrupted activation retains the pending-start
fence, original database backup and previous guest receipt for inspection/resume.

The helper runs only in the owned WSL installer or daemon-free image build. It
accepts no command, URL, filesystem destination, package choice or Docker context.
It rechecks immutable toolkit bytes and protects private root-owned journal,
configuration and locks. Existing conflicting runtime configuration is preserved.
It validates the merged config, enables live restore before any required owned
daemon restart, and compares every running container's exact ID, PID and start
time before and after activation. Changed processes prevent completion. Repeated
completed operations verify readiness without reinstalling or restarting Docker.
Subcommands use owned groups, bounded output/time and scoped cancellation.

This remains a qualification candidate. Actual image construction, preserving
Windows update, CPU conversation/recovery and GPU isolation/inference gates must
be reported separately. Neither successful toolkit installation nor a runtime
listing qualifies Windows GPU generation or the complete NR-13/14 requirement.

### Recorded installation and preserving-update evidence

On 2026-11-01, source `30abf9d` passed 232 affected Python tests, whole-tree
Ruff/format checks and production/development Compose validation. Actual Windows
PowerShell 5.1 passed 34 guest-update, 89 update-coordinator and 14 physical-storage
assertions. A clean application/Docker/Debian package, daemon-free guest image and
686,044,667-byte native Windows installer were built. Inspection as guest UID 1001
confirmed the installed toolkit and runc default without exposing the private
root journal; this image inspection did not run GPU inference.

The installed native setup coordinator then updated the retained Windows WSL
installation in place. Its original registration, complete database byte hash,
eleven private-data/registry table hashes and desktop configuration were retained.
A separate owned diagnostic container kept its exact ID, PID and start time
through toolkit activation and Docker restart. Repeating the completed helper
kept the same Docker daemon PID and confirmed the runc default. Existing model
weights were retained, without another model download.

After the update, the original account authenticated and its four-message
conversation remained available. An ordinary worker Run loaded the cached 4B
GGUF with the explicit 4096-token CPU profile; a separate normal Chat Run returned
the requested `WINDOWS_UPDATE_OK` response. A browser-automation acknowledgement
timed out after its load request had already succeeded. The independent observer
adopted that existing Run/instance instead of submitting another load. A bounded
one-shot authenticated API check completed the reply test without restarting or
terminating the existing browser, QA agent or station. This proves the CPU
regression path, not Windows GPU inference or an additional browser-button gate.

Normal application Stop intentionally shuts down its managed model. The diagnostic
container tests preservation during the subsequent installer operation; it does
not claim that a model remains running across an explicit Stop. A deadline-bound,
cooperatively released QA foreground client prevented WSL's ordinary idle exit
during this test, without changing global WSL configuration. Earlier observer
failures did not dispatch an update. The update used the same native coordinator
as the UI; this run does not qualify an additional UI-button interaction.

The retained VM has no GPU. Actual Windows GPU selection/inference, a fresh import
of this GPU-prepared image, native accessibility/signing gates and the complete
cross-platform release remain separate acceptance work. Linux inference and a
Windows CPU result cannot substitute for those observations.
