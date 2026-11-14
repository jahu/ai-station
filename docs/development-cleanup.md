# Finish each task by cleaning up

Cleanup is part of a task's definition of done, after implementation, review and
verification. Do not leave a growing collection of downloaded test models,
installed SDK copies, virtual machines or package trees for a later general cleanup.
This contributor policy does not authorize application agents to run arbitrary
commands or manage Docker; existing execution boundaries remain unchanged.

## Before creating large resources

- Reuse a compatible verified project cache or prepared environment when its
  ownership/security contract permits. Do not bypass inode, isolation or permission
  checks to share files. Do not repeatedly download the same qualified input.
- Give each temporary namespace an owner, purpose and source revision. Record
  process PID/start identity and container/image identities where relevant.
- Inventory resources using metadata and bounded reads; never read model weights
  as configuration. Distinguish Python path files in site-packages from binary
  `.pth` checkpoints, and cap the actual memory used by cleanup scans.
- Prefer a temporary context with final cleanup. Keeping failed fixtures must be
  an explicit diagnostic choice with a reason and bounded retention.
- Keep **at most one reusable Windows QA virtual machine** for this project.
  Do not create another full Windows installation for each task or release.
  Preserve any backing chain needed by that single VM. Temporary overlays and
  copied guest payloads belong to the task and are removed after export.

## Required task-close checklist

1. Export/check requested deliverables and retain concise evidence: source revision,
   commands/results, checksums, relevant logs and a small useful sample. A success
   receipt is not permission to discard user-owned artifacts or failed-check evidence.
2. Stop only helpers created for this task, after checking their exact process or
   container identity. Do not stop unrelated runtimes or the user's image viewer.
3. Remove obsolete owned test SDKs/model copies, package trees, rootfs/transfer
   parts and temporary fixtures once final outputs and necessary production copies
   are verified. Keep production Library media, models and installed environments.
4. Recheck canonical paths, symlink and hardlink relationships, `.pth` references,
   open files/processes, mounts, configured paths and registered resources. A name
   such as `acceptance`, `tmp` or an old date does not prove a resource is unused.
   A stopped container or idle model can still require its files/image later.
5. Remove only proven project-owned unused Docker images/containers by explicit
   identity, without force. Retain configured executor images, every referenced
   image, current release and useful rollback. Never use global Docker/volume prune
   or clean another project's cache. Do not sum virtual image sizes as freed bytes.
6. Keep the latest two published installer/QA/checksum sets; discard superseded
   expanded bundles after publication verification. Preserve required updater/VM
   inputs and verified database recovery points; never purge manual/user backups.
7. Measure actual filesystem free space before/after and verify affected services,
   resource readiness and retained outputs. Report what was removed, real reclaimed
   space and any resource intentionally retained, with reason and expiry/review date.

A task is not finished merely because code was merged. If evidence or an active
reference prevents cleanup, name the exact retained resource and follow-up condition;
do not silently retain gigabytes of fixtures. No routine confirmation is needed for
already authorized cleanup of proven unused task-owned resources. Important user
data, external infrastructure and uncertain ownership remain protected.
