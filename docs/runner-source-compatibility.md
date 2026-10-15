# Reusing the right native Runner

The launcher currently accepts any healthy Runner with the matching data root.
The native package version remains `0.1.0` across typed API additions, so this
does not prove that an already running process supports the checkout being
started. A healthy older process can be reused and reject new typed requests.

Expose a deterministic SHA-256 identity of the packaged native Python sources,
captured once when the native application imports. Compare it with the intended
checkout before building or starting the control plane. Identical native sources
may be reused across control-plane-only releases and different checkout paths.
Missing identity, source mismatch or data-root mismatch fail with an actionable
error. They never authorize stopping an existing Runner, canceling work or
changing a managed or external runtime. Network failure still allows the normal
owned native startup; its resulting health must pass the same identity check.

This is local startup compatibility, not authentication or remote attestation.
Hash only package Python files, with relative names and content; ignore bytecode,
Git state, deployment paths, data and secrets. Changes after application import
must not make an old process advertise new source. No database migration, new
execution capability or endpoint mutation is needed.

Verify legacy and mismatching healthy responses, identical-source reuse, source
change/path independence and captured identity stability. Verify the launcher
fails before Docker build or startup, then run normal checks and a real private
Unix-socket health probe. Deploy only after confirming the owned Runner is idle,
preserving the database and existing owned model instances.
