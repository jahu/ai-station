# Local model access through the Host Runner

A host model server bound to `127.0.0.1` is not reachable through Docker's host-gateway address. The control plane therefore supports a typed local-model bridge over its existing private Runner socket. Compose selects this transport by default. The native runner connects to the administrator-configured local endpoint; the existing runtime keeps its current bind address and ownership.

Only model listing and bounded streaming chat-completion requests are supported. Callers cannot choose an upstream URL, arbitrary HTTP method/path, headers, tools or credentials. The expected endpoint must match host configuration, local/private URL rules apply, and redirects are disabled. API keys remain in environment configuration and are not forwarded as request fields. Cancellation closes the upstream stream. Model work remains an ordinary worker Run; the API only queues it.

`AI_STATION_LLM_BASE_URL` is the host endpoint. Compose passes it as `AI_STATION_LLM_HOST_BASE_URL` to container clients using `AI_STATION_LLM_TRANSPORT=runner`. Existing direct container connections remain available with `AI_STATION_LLM_TRANSPORT=direct` and `AI_STATION_LLM_CONTAINER_BASE_URL`. Native development defaults to direct access. Runs snapshot the actual endpoint and fail if it changes before execution.
