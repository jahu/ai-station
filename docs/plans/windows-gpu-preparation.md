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
   Runtime registration can be [reloaded by Docker](https://docs.docker.com/reference/cli/dockerd/#configure-runtimes-using-daemonjson);
   actual owned-service reload and surviving CPU workloads must be verified.
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

These inputs are not yet activated by the guest builder or preserving updater.
The remaining installation/configuration and actual Windows GPU gates above
still apply; including files does not make a GPU profile ready. No host package,
driver, Docker daemon or model is changed by preparing this bundle.
