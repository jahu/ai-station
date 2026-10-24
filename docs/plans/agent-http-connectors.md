# Saved HTTP sources for agents

Agents can select one saved HTTP GET connection in Settings or their conversation
card. The operator reviews its address and authentication state; the model cannot
choose a URL, connection, header or credential. The same source can precede local
code/data processing or goal-based media preparation.

An optional agent scope freezes the connector ID and a policy revision. Migration
0034 adds its nullable JSON column; absent scopes serialize exactly like legacy
definitions. Address, authentication or enablement edits rotate authority;
health checks and display-name edits do not. Changed, disabled or removed sources
stop execution and require reselection. Secrets are resolved server-side only,
sent over HTTPS and scrubbed from captured responses before storage or inference.

The ordinary agent_tool child uses the existing public HTTP client (DNS/IP
validation, bounded bodies, safe redirects, no cookies), cancellation polling and
absolute workflow deadline. It saves an attributed, untrusted JSON observation.
Reports and research-to-local-code handoffs verify its original artifact bytes and
scope. Offline generated code gets the saved response, never credentials/network
authority. Historical captures remain inspectable after connector changes.

Normal tests use temporary databases and fake network/model responses. Verify
activation, authority changes, echoed-secret redaction, Stop/deadline, immutable
handoffs and desktop/mobile selection. Release qualification must distinguish
fake inference, actual public HTTP and private authenticated test fixtures.

Implementation now includes nullable scope migration 0034, activation/readiness,
server-side credential redaction shared with Check GET, fixed tool calling,
immutable report/research adoption and both agent editors. Qualification is still
pending; the live release remains #408 until the new reviewed head passes gates.
