# Open model discovery and installation — next release

Owner request, 2026-11-04: add new models after installation, by discovery or a
publisher link, and use them from the conversation, agents and media workspaces.
Hardware suitability must be assessed **before downloading**, on the actual
installation. This is the scope of the next feature release, not completed work
in 0.1.2. Working integrations, model files and user defaults must be preserved.

## Product journey

Models has **Installed**, **Discover** and **Downloads**. Discover opens on a
small ranked selection for this station; users may search or paste a model/file
link. Filters select Conversation, Images, Video, Voice, Music, Avatars and Memory.
Each result distinguishes publisher claims, supported operations, runtime
compatibility, hardware estimate and actual local qualification. Do not show a
wall of hundreds of barely differentiated files or a green badge based on tags.

The detail sheet explains what the model does, license/access requirements,
selected quantization, complete companion set, download/disk budget, GPU/RAM
budget, expected context or media profile, and why that variant was recommended.
One explicit Install action snapshots that plan. Progress, Stop, Resume and
history use existing Tasks/Runs. After verification and registration, the model
appears in compatible workspace selectors and agent/orchestrator tools. Installing
does not change a personal default or replace a running model without consent.

## Sources and compatibility

1. Reuse the curated starter recipes, installed ModelFile/Definition registry,
   immutable object store, downloader, Runner verification and managed runtimes.
   Do not build a second package manager or inference queue.
2. Add a source-adapter boundary. Hugging Face is first: bounded search plus
   repository/file URL parsing and immutable revision/file metadata resolution.
   Future Civitai/other adapters must provide the same provenance and identity
   contract. Unknown hosts are never arbitrary downloader endpoints.
3. Separate a **source observation** from an **installation plan** and a
   **qualified runtime binding**. Resolve mutable links to commit + file SHA256
   + exact size. Metadata is untrusted data, not executable instructions. Model
   cards, popularity and filenames never grant tool permissions or code execution.
4. Compatibility is per runtime version, model architecture, component role,
   format/quantization and operation. A GGUF may be an LLM, image transformer or
   vision projector. A safetensors file may be a checkpoint, LoRA or companion.
   Family names/tags alone do not prove interchangeability.
5. New checkpoints of supported architectures can use validated recipe slots
   with frozen required companions and runtime identities. New architectures
   require a supported adapter/recipe; show the concrete missing requirement.
   Never execute repository Python, pickle, remote custom code, install scripts
   or arbitrary workflows to make an unknown model appear compatible.
6. User review of a server-resolved manifest extends the existing curated-only
   admission. API clients cannot select destination paths, commands, SDK URLs or
   replacement expected hashes. A changed observation requires a fresh review.
   Gated models report access requirements; credentials remain secret references.

## Hardware recommendations

Use live native telemetry, installed runtime/platform capability and free space
on the actual application backing volume. Never assume a GPU count or pool two
GPUs unless the chosen adapter supports that exact sharding strategy.

- LLM: weight/quantization, architecture-specific KV cache, context, graph/state
  reserve and per-device headroom. Recommend a fitted context and variant; a model
  that barely loads at 4K is not a recommendation for a 100K task. Reuse existing
  llama.cpp fitting and verify against actual GGUF metadata before activation.
- Media: use validated workload profiles for resolution, batch, duration/chunk
  size and model/component residency. File size alone cannot predict VRAM.
  Account for text encoders, VAEs, vocoders and motion/face components, not only
  the main checkpoint. Multi-GPU needs actual adapter support.
- Separate capacity from temporary occupation. Show **fits when resources are
  free**, **busy now**, **too large**, **unknown requirements** and **unsupported
  runtime** independently. Missing/invalid sensors are unknown, never zero/free.
- Disk includes missing weights, runtime preparation, staging and safety space;
  reuse verified object identities. Recheck before and during transfer. Include
  host physical-volume limits on Windows, not only guest filesystem free space.
- No implicit CPU/RAM offload, swap, cloud substitution, eviction of external
  processes or driver modification. Any CPU/offload option is explicit.
- Estimates are not benchmarks. Actual first-result qualification can promote an
  exact model/runtime/workload/hardware observation; never predict token/s or
  film quality from a download count. Failed loading retains the installed object
  and actionable diagnostics rather than selecting another model invisibly.

## Discovery ranking

Rank usable profiles ahead of merely downloadable files: installed/reusable,
supported on this runtime/platform, fits requested workload, publisher provenance,
license/access, download cost, then recency/popularity. Preserve explicit user
choice. Bound HF requests and result counts; do not crawl the Hub or fetch every
model card. Refresh only on user discovery/explicit update checks; no startup
model downloads and no silent catalog subscription. Never upload hardware serials,
local paths, prompts or private Library contents to model sources.

## Delivery sequence and acceptance gates

1. Source resolution/search, hardware assessment contract and private durable
   inspection Runs, including invalid links/metadata, cancellation, claim fences,
   privacy and SSRF tests. This is discovery, not installation completion.
2. Discover/detail UI: search and paste, clear compatibility and fit reasons,
   source/license links, meaningful variant choice and saved inspection history.
   Test desktop/mobile/keyboard and real public metadata without downloading weights.
3. Dynamic GGUF install plans: immutable server-side manifest, explicit consent,
   existing resumable download/verification/adoption, native header admission,
   fitted context, shared registry/private history and one first local reply.
4. Parameterized recipe slots for image, video, speech/music/avatar and memory:
   verify checkpoint/companion compatibility, persistence and runtime binding.
   Qualify at least one newly discovered compatible model per applicable family;
   unsupported architecture is visibly blocked, never a fake working integration.
5. Unify selectors and auto routing over those bindings. Freeze selected model,
   recipe and workload in each Run. Agents inherit operation compatibility;
   installation/admin authority is never inherited by the orchestrator.
6. Complete ranking, refresh/removal/update ownership and retry/recovery tests.
   Add operator QA, README/website/release notes and Linux/Windows installer
   qualification. Keep macOS status unchanged. Reviewed PRs go to develop;
   master promotion still needs the human owner before release publication.

Completion requires the user journey, not merely a model search endpoint. Every
deliverable above remains in scope until evidenced. Normal tests use fake metadata
and tiny files; real model downloads/inference must be explicitly identified.

Primary source contract: [HF Hub API](https://huggingface.co/docs/hub/api),
[HF model metadata client](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api).
