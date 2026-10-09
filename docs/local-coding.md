# Local coding proposals

The local coding adapter extends the existing bounded proposal workflow: Task → owned worktree preparation → local model proposal → checked file replacements → configured validation → review → optional reviewed commit. The model receives UTF-8 source snapshots and project guidance through the configured local inference endpoint or an owned llama.cpp instance. It can optionally find the relevant files with typed read-only repository tools and, during that exploration, GET public pages or query configured search. It never receives shell access or a browser.

The control plane snapshots the model and project configuration. Managed llama.cpp loading is a normal prerequisite Run; active coding consumers protect their model from idle eviction. Native request ownership, process-group cancellation and conservative interrupted-run recovery use the same contracts as Cursor. Model output must be one bounded JSON proposal for selected paths; malformed, truncated, tool-calling or failed responses never authorize writes. Worktree identity and input hashes are checked again after inference.

Local execution requires filesystem_read, workspace_write, git_read and network_read for the configured local inference bridge plus public GET/search during exploration. It grants no external_ai permission, caller-selected inference URL, model installation, POST to arbitrary hosts, browser automation or arbitrary command execution. Secrets remain in the Runner's configured provider; the coding subprocess communicates over its private Unix socket. A confirmed proposal produces the existing diff and JSON review artifacts and queues trusted project validation. Successful generation does not mean successful validation or approval.

Repository exploration can select the source context automatically; code application remains a checked proposal followed by saved validation. Failed validation offers an explicit local repair action and an opt-in budget of up to two automatic repairs. Uncertain or interrupted work is never automatically retried; push, merge and deployment remain separate. Cancellation/interruption preserves any partial worktree changes for inspection.

Code proposals use an 8192-token response budget; short source-discovery replies retain 2048 tokens. Each streaming response has a 15-minute wall-clock limit and the complete job (including exploration) has a 20-minute deadline, with a five-minute idle timeout. Progress logs report generated character counts without exposing incomplete source. Explicit cancellation still closes the owned process and inference connection. Choose a context size that accommodates the selected source text before first model load. Truncated output is rejected rather than partially applied. Normal integration tests use a fake UDS inference service and real disposable Git repositories; real local-model verification is explicitly opt-in.


Verification on 2026-09-29: real Qwen 27B Q4 inference through the existing two-GPU llama.cpp runtime changed a README in a disposable owned worktree and produced a review artifact. The source checkout and Git index were unchanged. This proves bounded local proposal execution, not autonomous repository exploration. Validation/commit, malformed and truncated replies, cancellation, request replay and saved-model reload use isolated integration tests with fake inference. The Assistant supports Local AI coding as well: choose Coding with Local AI, select a project and files, then send the instruction. It uses the conversation model and shows the same child Runs and review artifacts inline. Cursor remains a separate action with explicit external consent.

To repeat the real inference smoke using an already-ready owned runtime:

```bash
AI_STATION_REAL_LOCAL_LLM_TESTS=1 \
AI_STATION_SMOKE_RUNNER_SOCKET=/absolute/path/to/runner.sock \
AI_STATION_SMOKE_LLAMA_INSTANCE=<ready-instance-uuid> \
.venv/bin/pytest -q backend/tests/test_projects.py -k test_real_local_coding_proposal
```

The smoke does not load or stop models, modify registered projects, or create a production conversation. It forwards only the disposable test's source snapshot through the private Runner bridge.

## Automatic source discovery

In Coding → Local AI or Assistant → Coding with Local AI, keep **Let Local AI find the relevant files** enabled. Choose the project/model and describe the task; no manual file list is required. The Runner allocates the usual fresh worktree, then accepts typed `list_files`, literal `search_files`, `read_file`, `fetch_url`, optional `web_search` and `finish` operations. The final selection enters the existing proposal, validation and review path. Disable the switch to retain explicit file selection (that path has no web tools). Cursor and Codex exploration stay repository-only.

When web tools are enabled, up to three public http(s) URLs written in the task are fetched automatically before the model's first request (same GET rules; private/loopback skipped). Those page excerpts are passed into the later code-proposal prompt as untrusted `web_observations`; exploration-only fetch is not enough. Local AI exploration then allows up to twelve model requests within the job's bounded deadline; Cursor/Codex keep eight and do not prefetch. Listings return 100 paths per page, search examines at most 500 matching paths and returns 30 matching lines, and reads retain the existing 32 KB/file source boundaries. `fetch_url` is GET-only: the URL must be public http(s) on port 80/443, DNS-resolved addresses must all be global unicast, redirects are re-checked, bodies are capped at 256 KiB and visible text at 8 KB, and script/style are stripped. Same-origin public links may be returned so later GETs can follow a site. Binary responses are skipped. JavaScript is not executed; a client-rendered site may yield little useful HTML. `web_search` is advertised only when the Host Runner has `AI_STATION_WEB_SEARCH_URL`; it sends only the query to that configured SearXNG service and returns up to five public snippets. Compose keeps SearXNG off host ports, so runner-side search stays off unless the operator points the runner at a reachable search endpoint. Git supplies tracked paths; hidden/credential paths and symlink escapes are excluded. Model output never becomes a command, inference endpoint or shell. Invalid operations, non-public URLs, incomplete responses and exhausted budgets fail before proposal application. Requests appear in captured output; successful review artifacts preserve all observations and emit `coding.exploration.completed`. Expand Repository exploration in the review to inspect them. Fetched pages and snippets are untrusted reference data, not proof that the generated site matches the live one.

The real-model opt-in test also accepts `AI_STATION_SMOKE_LOCAL_MODEL` and `AI_STATION_SMOKE_LOCAL_ENDPOINT` when using the Runner's already configured local server instead of `AI_STATION_SMOKE_LLAMA_INSTANCE`. Normal tests remain fake-inference only.

Verified 2026-10-06 with the existing local `qwen3:8b` provider: list repository files → read the introduction → select its path → generate and apply the expected replacement in a disposable owned worktree. Original checkout and index remained unchanged. A first real attempt exposed reasoning truncation; structured coding prompts now explicitly request JSON without reasoning, and the corrected real test passed. Fake-provider tests cover the shared validation/commit workflow, malformed operations, path boundaries and cancellation during exploration.


## Repair failed validation

When a completed Local AI proposal has confirmed failing project checks, its review shows **Repair with Local AI**. One click queues a new cancellable Run in the same owned worktree. It reuses the original model, selected files (including automatically discovered context), project guidance and snapshotted commands. The prompt includes bounded, redacted failure output; output is reference data, never a command or permission grant.

The new Run links to the failed validation and previous attempt. Its review compares all scoped files against the task base, including changes from earlier attempts. Validation runs again with the original commands. Old proposals become superseded and cannot be committed; accepting the latest successful result still requires explicit review. No cloud model, extra file scope, push or merge is introduced. Cancellation or uncertainty preserves work for inspection and never starts another attempt silently.

Normal integration coverage uses fake local inference, the fake sandbox helper and real disposable Git worktrees. It verifies selected/discovered scope, failure diagnostics, native scope checks, dispatch replay, cancellation, cumulative diffs, passing revalidation and the final reviewed commit. This is not a real-model repair smoke test.


## Bounded automatic repair

In **Coding → Local AI** or **Assistant → Coding with Local AI**, choose **Automatic repair**: off (default), one attempt, or two attempts. Only a confirmed failing validation report starts another attempt. The saved budget travels with every child Run and cannot be increased by model output. Success, cancellation, interruption, proposal execution failure or budget exhaustion stops the chain. A stopped/unknown runtime can leave a recorded repair-unavailable event instead of silently duplicating execution.

Each attempt uses the same model, original file scope, worktree and saved validation commands. Review shows attempts used and links to the successor; exhausted budgets remain explicit. The Assistant keeps historical failed checks visible but uses the current repair outcome for the task status. Committing remains a separate reviewed action. Fake-inference integration tests cover default-off behavior, one/two-attempt exhaustion, successful stopping, canceled validation and transactional rollback when model preparation is unavailable. Real-model automatic repair has not been smoke-tested.


On 2026-10-08 a real three-file website proposal hit the former 2048-token cap after 122 seconds of inference. Model loading and exploration had succeeded; complete-response validation correctly prevented any write. The proposal budget and overall deadline now accommodate longer local generation, while truncated responses still fail before applying files and identify the output/context limit explicitly.


## Coding context and GPU memory

Managed llama.cpp Coding runs load the largest practical Q8 KV context that fits the selected GPUs with Flash Attention, `--gpu-layers all` and `--fit off`. 131,072 is a ceiling sent by the Coding picker, not a promised load size. The control plane estimates VRAM from discovered GPU totals and the GGUF size, persists the fitted `context_size`, and records observed `n_ctx` from the owned server after it becomes ready. Advertised `n_ctx_train` is not treated as the running context. Missing VRAM totals use a conservative 16,384-token Coding fallback or a previously proven success for that model, GPUs and Q8 cache. CPU loads keep the 4,096-token floor. Known allocation failures are not retried at the same size.

When an idle owned runtime is smaller than that fitted target or still uses f16 KV, a stop → load prerequisite chain replaces it on the same saved GPUs before coding starts. Active consumers prevent replacement. Failed loads block coding instead of silently reducing context or offloading layers to CPU/RAM. Chat keeps its saved 4,096/f16 preset unless the user chose otherwise. External local servers retain their administrator-configured context. Source snapshot limits remain ten paths, 32 KB per file and 64 KB total; a larger model context does not send 100k tokens of repository input.
