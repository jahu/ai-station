# Clean Linux consumer installation (NR-13)

Preserve the full 0.1.0 contract in [next-release-0.1](next-release-0.1.md).
This increment qualifies an actual Linux OS installation and fixes its observed
consumer blockers. It does not qualify Windows/macOS or all graphics hardware.

## Actual environment and first finding

On 2026-10-31 a separate KVM guest booted the hash-verified official Ubuntu
24.04 amd64 image from the
[20261017 publisher directory](https://cloud-images.ubuntu.com/noble/20261017/).
QEMU and its dependencies were extracted into private project tools; the host OS,
Docker daemon, user groups, GPU devices and existing services were not changed.
The guest has its own writable disk, four CPU threads, 8 GiB RAM, no host mounts
or GPU passthrough, and SSH forwarded only on host loopback. Its initial account
had no Docker installation or Docker-group membership.

The reviewed `a985459` source built the actual Debian package with bundled Python,
native code and compiled application image. Installing that package through the
guest's real package manager correctly installed Zenity, Docker and Compose.
First launch nevertheless failed: the daemon works for the guest administrator,
but the new ordinary account cannot open its socket. The existing desktop
message offers no guided resolution. A successful extracted package on the
developer workstation had not exposed this problem.

## Intended first-start correction

Detect this specific local rootful-Docker permission condition separately from
a stopped daemon, missing Compose, unsupported platform or remote context. Offer
an explicit native setup step, before normal application startup, explaining
the requested account access. Keep existing working rootless/Desktop/configured
contexts unchanged. Cancel must leave the account/system unchanged.

Docker documents that [membership grants root-level access](https://docs.docker.com/engine/install/linux-postinstall/).
The dialog must disclose that fact and require the OS authentication agent;
the app/API must never collect an administrator password. This is a one-time
installer permission action, not a workload, Host Runner operation or agent tool.
Normal execution remains user-level. Do not automatically start/reconfigure
unrelated daemons, make the socket world writable, install drivers or change CUDA.

Prototype one root-owned, argument-free package helper which authorizes only
the invoking local account's Docker-group membership. Use the OS-provided
`PKEXEC_UID`, validate the account/group/socket again and refuse ambient caller
commands, paths, usernames or additional arguments. A matching
[polkit action](https://www.freedesktop.org/software/polkit/docs/latest/pkexec.1.html)
requires fresh administrator authentication, with no implicit or retained grant.
Its fixed purpose is account setup; it must never invoke application/user code
as root. Resume the app under the same ordinary UID with the new group available,
or present a clear sign-out/reopen step if safe group activation is unavailable.
Do not promise immediate continuation until exercised with the actual installed
package and OS session. Rootless alternatives remain a separately reviewed path.

## Required acceptance

1. Test detection of permission denial versus other Docker failures, cancellation,
   unsafe helpers/socket ownership, arbitrary extra arguments and unchanged
   working configurations. Review every privileged line and package path.
2. Install the final OS package into this clean guest and render the actual native
   consent/authentication flow. A cancellation makes no privilege change; only
   approved setup grants the current account access. No host changes are allowed.
3. Use the packaged interpreter/supervisor and a real browser to create the first
   admin, prepare the exact CPU engine/model and obtain a real selected-model
   reply. Inspect actual no-GPU/RAM limits and stop the owned model normally.
4. Close/reopen/background/Stop through real desktop controls, without duplicate
   services. Retain private cookies, account, conversation, memory, artifacts and
   selected model through restart.
5. Upgrade to a separately built package version through the real OS package
   manager, retaining the running version until an explicit idle restart.
   Remove/reinstall the package; preserve user data/version directories unless
   separately removed by an explicit user action. No package removal hook may
   delete models, credentials, histories or unrelated Docker resources.
6. Run affected tests, desktop packaging, source/asset identity and secret/data
   exclusion checks; inspect the full PR and local gates before merging into
   `develop`. Keep other supported-distribution, OS and hardware gates explicit.

Private source, disk, package, process identities and real results are retained
under `data/acceptance/linux-clean-install-20261031/`. The initial failure is
evidence to fix, not a waived acceptance or a successful consumer install claim.
