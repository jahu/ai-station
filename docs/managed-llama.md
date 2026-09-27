# Managed llama.cpp runtimes

llama.cpp and the configured OpenAI-compatible provider (including Ollama) coexist. Discovered GGUFs are loaded only by an explicit model selection. The native Host Runner owns a narrow container adapter; the control plane receives neither a Docker socket nor model-root mounts.

A load Task creates a Run and a managed RuntimeInstance. Its immutable request binds the model path, observed size/mtime, selected discovered GPUs and context size. The Runner uses an administrator-configured, already installed image, resolves its immutable image ID, mounts one model read-only and one private runtime directory, drops capabilities, runs as the workstation user and disables networking. llama-server listens on a Unix socket in that directory. No image/model download, driver change or external-runtime shutdown occurs.

Multiple GPUs use llama.cpp layer splitting with equal proportions across the explicitly selected devices. GPU reservations remain held while the runtime is loaded, independently of the completed load Run. Stop is a separate typed Run and releases reservations only after confirmed termination. The immutable native manifest and container ID/labels identify ownership across restarts. Repeating a load request for the same instance inspects/resumes its create/start journal; it never creates a second container or restarts an exited instance. Recovery can safely resume that operation. External containers are never adopted.

Inference uses the private Runner bridge and a runtime ID, not a caller URL. A stored conversation retains its model identity. A stopped model must be loaded again; changing runtimes does not silently substitute another model. The initial UI offers load, ready-model selection and stop; automatic eviction/reloading during multi-step plans follows separately.

Configuration: `AI_STATION_LLAMA_IMAGE` selects an already-installed llama.cpp server image. Its CLI must support `--host /runtime/model.sock`, `--split-mode layer`, `--tensor-split`, `--gpu-layers` and `--parallel`. Docker/NVIDIA Container Toolkit compatibility is checked by actual startup. No driver is installed or changed.

## Verified local acceptance (2026-09-27)

Real tests used the installed llama.cpp server image with CUDA 12.8, build b11011. The 27B RVN Q4_K_M GGUF loaded across two discovered RTX 3060 devices, answered through the private Runner bridge and unloaded through a stop Run, releasing both resource locks. A browser test selected that model, created a conversation and displayed its actual response. The 9B Q6_K GGUF independently passed load/chat/stop on one GPU. Model files and the external Ollama service were unchanged. These tests used isolated application databases.

The installed CUDA 13 server image required CUDA 13.3 and failed its driver compatibility check; the existing CUDA 12.8 image worked without any host changes. The 27B IQ2_XS variant is discoverable but has not yet been smoke-tested in this increment.
