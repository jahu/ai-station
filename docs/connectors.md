# Named connectors

The System workspace lists connectors with their actual status. Only **HTTP GET** of one reviewed public URL is operational. Named HTTP connectors are one keyboard sequence (arrows, Home, End, Enter inspects the last check when one exists) with unique Inspect names; Check GET and Remove stay on the selected row. Browser automation, a general GitHub connector, email, calendar and social adapters remain listed as unavailable; that unavailable list is a separate keyboard sequence (arrows, Home, End) with unique Adapter names and no inspectable adapter Run. GitHub publication still uses the existing Host Runner `gh` path and is not this registry.

An HTTP connector stores a unique key, display name, public `http`/`https` URL on port 80 or 443, optional secret reference (`env:NAME` or a write-only file under the data root) and enablement. The API never returns a secret value. URLs cannot embed credentials. Private, loopback, link-local and non-public DNS answers are rejected, including after redirects.

**Check GET** queues an ordinary Task/Run (`http_connector`) with `network_read`. The worker repeats the public-address checks, optionally sends `Authorization: Bearer <secret>`, records events and a JSON artifact, then updates `status`/`health`. A missing secret fails closed before enqueue. Cancellation of a queued or running check does not invent a healthy result. Retry is inspect-and-new-Run only; the same check is never silently replayed.

Agents do not receive model-selected connectors in this increment. Unpublished SearXNG stays unpublished; Chat/agent search is unchanged.

Normal tests mock HTTP and never call the public internet.

Public connections are pinned to checked IPs. A redirect to another origin drops all configured secret headers; cookies from responses are not replayed. See [connection identity](security-model.md#public-connection-identity).
