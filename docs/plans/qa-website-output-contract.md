# Website completion requires an actual build output

AGENT-005 produced HTML/CSS and an npm build command with exit code zero, but
that command only printed a message. No dist directory or preview/download was
produced. AGENT-006 follow-ups also exposed malformed local proposals and
rejected duplicate/out-of-scope paths; preserve those separate failures.

For an explicitly reviewed website-building agent with automatic checks enabled,
freeze a controller-owned `static_site` output expectation on its coding Run.
It remains part of the existing private execution snapshot, is copied into
validation, and survives the existing same-worktree follow-up/repair parameter
copy. This does not alter project commands, permissions, approved file scope or
generic CLI/library validation. No database column or migration is needed.

Successful command exit alone cannot satisfy that expectation. Use the existing
verified build ZIP and require its nonempty root index.html. Preserve the real
native exit codes, add an explicitly control-plane output check to the report,
and fail validation with its missing-output reason. Feed that reason through the
existing bounded repair prompt; do not fabricate a failing native exit code.
An absent detected build command must also produce a real failed validation
check rather than the generic not-configured success path. No empty command
request should be sent to the Host Runner.

The typed native validation request also freezes the static-site expectation.
Before a website build, move any previous ordinary dist directory into that
Run's owned scratch directory, without deleting it. Reject redirected dist
entries. Thus an echo-only rebuild cannot publish stale output. Generic builds
retain their existing behavior. The native report must echo the frozen contract.

Archive path/hash/member/security checks remain strict. Existing successful
generic builds without a dist export retain their current warning behavior.
Untrusted generated summaries or files cannot replace the frozen expectation.

Required qualification: explicit/non-website intent distinction, bound snapshot
tamper rejection, no-command and exit-zero/missing-output failure, a verified
nonempty index success, unchanged generic builds, bounded repair and preserved
continuation scope. Then rerun the actual website agent in the browser, inspect
the real preview, download its build, and test the same-worktree follow-up.
This document describes work in progress, not completed acceptance.
