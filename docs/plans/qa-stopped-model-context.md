# Auto retains actual context proof after a model stops

The WORK-002 post-deployment test failed after image generation stopped the owned
9B model. Its final process observation contained only `stopped`/`alive=false`,
overwriting the earlier `n_ctx`. Auto then treated the historically qualified
9B as unproven, chose a larger estimated model and reached only 65536 actual
tokens. The failed test remains recorded; a manually warmed model is not a fix.

For a stopped instance whose current observation omits actual context, Auto may
use the `n_ctx` measured in its successful load's existing `runtime.ready` event.
The event must name that instance, identical GPU selection and q8 cache. All
existing file size/mtime, profile, status and successful-load checks still apply.
The requested allocation caps the measurement; requested context alone is never
proof. Current ready instances cannot use this stopped-instance fallback.

This is a read-only projection over existing events, not a migration or rewrite
of old observations. Loading, resource management, permissions and the final
actual-context guard before code generation remain unchanged. Tests use the
real stop-observation update and reject mismatched or incomplete event proof.
Final acceptance requires the exact CSV request while the qualified model starts
stopped, followed by a real download and verification of the resulting file.
