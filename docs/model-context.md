# Local coding context

Coding requests up to 131072 tokens with Q8 KV cache. This is a ceiling, not a promise of allocation or useful output quality. The native Runner reads a bounded, read-only GGUF header during the load Run, before dispatch, to estimate KV storage from architecture, layers and attention dimensions. Weight quantization changes weight storage; it does not change the attention cache dimensions.

Supported dense Llama/Qwen architectures use all attention layers. Qwen3.5 uses its declared full-attention interval, with an additional reserve for recurrent state. Unknown or unsupported headers retain the conservative existing fallback. Header inspection never reads tensor data, edits a model, downloads dependencies or runs inference. Model identity must still match the discovery observation.

The worker retains the requested ceiling, allocated estimate and metadata provenance in the Run/runtime. Allocation also reserves CUDA overhead and free VRAM headroom. The running server's reported context remains authoritative. Recovered dispatched loads retain their original request. Cancellation during inspection prevents dispatch. No HTTP handler parses model files.

Reference formats: [GGUF specification](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md), [llama.cpp Qwen3.5 attention layout](https://github.com/ggml-org/llama.cpp/blob/master/src/models/qwen35.cpp).

Real hardware acceptance is recorded separately; a header estimate alone does not prove that a long prompt was processed successfully.

## Workstation acceptance — 2026-10-13

The existing RVN 27B IQ2_XS GGUF loaded through an ordinary runtime Run on both detected 12 GiB GPUs. llama.cpp reported `n_ctx=131072` and `n_ctx_train=262144`. Chat completed both a short Polish answer and a synthetic capacity test with **110029 input tokens**, returning the requested `CONTEXT_OK`. That test verifies processing a long input, not correctness on a complex software project.

A separate name-only project was created through the API. Local Coding produced `calculator.py` and `test_calculator.py` in an isolated owned worktree; a normal validation Run executed Python unittest successfully. No commit, push or merge was requested for that acceptance project. Evidence is kept locally under `data/acceptance/gguf-context-20261013/`.

For the installed 27B Q4_K_M file, the new header-based estimate on these GPUs is 92160 tokens rather than the previous size heuristic's roughly 29K. This larger allocation is not yet a real load smoke test. The installed 9B Q6_K and 27B IQ2_XS both estimate at the 131072 ceiling; only the IQ2_XS allocation and long-input inference are verified here. Runtime-observed context remains authoritative.
