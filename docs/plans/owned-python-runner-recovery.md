# Native Runner crash recovery acceptance

Extend the existing explicit CPU recovery probe with a native failure target.
Use its disposable database/repository/private Unix socket and installed Python
image. Kill only the test-created native Runner while its CPU job is actually
running. The original worker must observe the lost transport and preserve the
Run for inspection, rather than fail/requeue it or dispatch again. Start a new
native process against the same isolated ownership journal/socket.

The new Runner must identify the same live owned process by persisted identity,
retain its original deadline and permit typed per-Run cancellation. Exercise both
natural completion and operator cancellation. Recovery must end interrupted or
canceled respectively, without adopting uncertain output or replaying execution.
Verify the same native job PID, one script start, confirmed owned-container
cleanup, original fixture bytes and no Library publication. Keep failed evidence
and preserve an uncertain workspace. The working AI Station, models, private
access daemon, credentials and external services must stay untouched.

Normal test behavior and the existing worker-failure default stay unchanged.
The opt-in flag remains mandatory and the command cannot build/pull images.
This qualifies these actual native-loss paths, not machine reboot, every adapter,
or sustained multi-GPU concurrency. Document exact commands and reviewed-head
evidence, review the full diff and merge to develop only after local checks pass.

Actual 2026-10-25 acceptance passed both native-loss cases: the original worker
recorded transport loss, the new private Runner adopted the same live job PID,
and completion/cancellation ended interrupted/canceled without replay or output
adoption. Exact owned containers were removed and fixture/index/script bytes
survived. The unchanged default worker-failure mode also passed both actual cases
on this final script. Evidence is under
`data/acceptance/owned-python-runner-recovery-20261025/{actual,actual-worker}`.
All four use the already installed CPU image; no model/GPU/download or live
deployment work occurs. Full-source Ruff/format, explicit opt-in guard and
production-source identity determine reviewed-head qualification. Existing #428
application gates can be reused only after confirming those inputs are identical;
final qualification/review/merge receipts remain authoritative.
