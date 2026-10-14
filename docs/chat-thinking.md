# Optional local thinking

Chat supports an off-by-default **Thinking** switch for owned llama.cpp models
whose on/off behavior has been checked. Select an installed model, open its model
picker and expand **Thinking support** to run the check. This creates an ordinary
Task/Run, loads the selected model through the existing prerequisite if needed,
and performs two short local replies. The check has Stop and an inspectable Run.
Repeated requests reuse the pending check; failure never enables the switch.

The result binds the model observation (size/mtime), owned container image identity
and chat-template SHA-256 to a successful qualification Run. The catalog reads
that proof without inference. A changed model, image or template requires a new
check. Qualification leaves the runtime available; it does not unload a model
another conversation may use. External/unmanaged endpoints and Work executors do
not advertise this control. No model weights, images or dependencies are downloaded.

Per-turn `reasoning` is a strict `{enabled: boolean, budget: integer}` structure.
The budget is 32–1024 tokens (UI uses 256); enabled turns require at least 256
additional output tokens for a final answer. The native typed owned-runtime path
maps this to llama.cpp `chat_template_kwargs.enable_thinking`,
`reasoning_format=deepseek`, and `reasoning_budget_tokens`; explicit Off also sets
`reasoning_effort=none`. The generic host inference bridge rejects these controls.
The installed llama.cpp build 11011 / `aa39d7a3e` supports these request overrides;
support is still qualified per model rather than inferred from the CLI flag alone.
No arbitrary generation JSON or unverified Low/High effort slider is exposed.

Reasoning deltas are bounded, stored in assistant-message metadata and emitted as
`chat.reasoning_delta`. The transcript displays them in a collapsed plaintext
Thinking disclosure. Final answer content remains separate, so conversation
context and summaries do not copy reasoning traces. Stop closes the stream;
output-budget exhaustion fails visibly and preserves partial output. Existing
clients and accepted receipt fingerprints without `reasoning` remain compatible.

Verification: temporary-DB/fake-provider tests cover qualification, unsupported
models, changed runtime/file observations, metadata tampering, repeated checks,
lease recovery, cancellation and partial output. Frontend tests cover unavailable
controls, Chat/Work switching and request mapping. A real isolated local
Qwen3.5-9B-Uncensored Q6_K check passed Off/On and a subsequent thinking Chat turn,
receipt replay and typed model stop. The production database was not modified by
that smoke. Evidence: `data/acceptance/chat-reasoning-20261014/real-result.json`.
