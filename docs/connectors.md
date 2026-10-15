# Named connectors

The System workspace lists connectors with their actual status. **HTTP GET** of one reviewed public URL and read-only **GitHub repository snapshots** are operational. Named HTTP connectors are one keyboard sequence (arrows, Home, End, Enter inspects the last check when one exists) with unique Inspect names; Check GET and Remove stay on the selected row. Account browser automation, email, calendar and social adapters remain listed as unavailable; that unavailable list is a separate keyboard sequence (arrows, Home, End) with unique Adapter names and no inspectable adapter Run. GitHub publication still uses its separate, approval-bound Host Runner adapter.

An HTTP connector stores a unique key, display name, public `http`/`https` URL on port 80 or 443, optional secret reference (`env:NAME` or a write-only file under the data root) and enablement. The API never returns a secret value. URLs cannot embed credentials. Private, loopback, link-local and non-public DNS answers are rejected, including after redirects.

**Check GET** queues an ordinary Task/Run (`http_connector`) with `network_read`. The worker repeats the public-address checks, optionally sends `Authorization: Bearer <secret>`, records events and a JSON artifact, then updates `status`/`health`. A missing secret fails closed before enqueue. Cancellation of a queued or running check does not invent a healthy result. Retry is inspect-and-new-Run only; the same check is never silently replayed.

Agents do not receive model-selected connectors in this increment. Chat/agent search is unchanged.

Normal tests mock HTTP and never call the public internet.

Public connections are pinned to checked IPs. A redirect to another origin drops all configured secret headers; cookies from responses are not replayed. See [connection identity](security-model.md#public-connection-identity).

## GitHub repositories

Connectors → GitHub accepts `owner/repository`, with no credential field.
Connect saves metadata only; Refresh repository enqueues a `github_read` Run
with `network_read` and `github_read`. The native Runner uses the operator's
existing `gh` session; the control plane never reads or copies credential files.
Missing CLI/login/access fails visibly rather than installing or authenticating.

A fixed GET snapshot contains repository details and at most 30 open entries
per issue/PR list. Issue-list entries can include PRs before filtering, so this
is a bounded observation rather than a promise to return every open issue.
Bodies, comments, source files, arbitrary API paths and caller queries are excluded.
The UI keeps the snapshot visible while refreshing or after a later failure,
shows its capture time and error, and links to GitHub, Run history and stored JSON.
Changing the configured repository invalidates the displayed target's snapshot.
Disconnect removes local connector metadata; past Runs/artifacts and the remote
repository remain. Agents receive no implicit GitHub access.

The job has a 60-second deadline, bounded output, exact run/request ownership and
a private persisted request. Repeating the same Runner dispatch returns the owned
process or fails for inspection; it never launches another uncertain job. Standard
owned-group cancellation and stale-lease recovery apply. A canceled/interrupted
job cannot adopt a successful snapshot. No writes, notifications, PR merges,
credentials or OS changes are exposed by this connector. General GitHub actions
remain separate capabilities requiring their own permission/approval contracts.

Normal tests use fake gh processes and temporary databases, including cancellation,
request replay, invalid target/permissions, secret-safe errors and snapshot history.
An opt-in actual API/worker/native read of `jahu/ai-station` passed on 2026-10-15;
evidence: `data/acceptance/github-read-20261015/real-result.json`. It performed
only fixed GET requests and stored/retrieved the JSON artifact.
