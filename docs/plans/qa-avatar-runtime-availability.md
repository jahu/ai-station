# Unavailable avatar setup is visible before execution

AVATAR-004 showed an unavailable Echo runtime as ready to generate. A new job
was accepted and waited for 24 GiB RAM rather than explaining missing setup.

The workspace now disables submission while setup is loading, unavailable or
cannot be checked, with a clear setup notice and the existing System link.
The submit handler also checks readiness so keyboard submission cannot bypass
the button. A failed readiness refresh cannot reuse stale available data to
enable submission. Existing jobs remain visible and keep their Stop controls;
new Resume attempts recheck setup for standard as well as reduced-RAM profiles.
Acknowledged request replays still return their original receipt.

The shared avatar memory-admission function checks setup for standard and
reduced-RAM profiles before new Tasks/Runs or speech are created. An empty legacy
profile rechecks availability without changing the saved appearance recipe,
request, prior segments or replay identity. Runtime availability is distinct
from temporarily busy RAM/GPUs: valid setup still uses ordinary resource queues.

Tests cover short/full jobs with recording/typed speech, no queued work after a
setup denial, and the existing successful synthetic lifecycle and recovery.
Frontend tests cover loading, failure, unavailable setup and submission guards.
Final acceptance requires actual compiled desktop/mobile browser checks against
an owned isolated unavailable setup; never disable the workstation's working
runtime just to produce this condition.
