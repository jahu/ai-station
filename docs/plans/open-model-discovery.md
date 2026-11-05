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

Owner clarification, 2026-11-05: assessing whether a download makes sense on
the machine running AI Station is a mandatory part of discovery and installation,
not an optional benchmark after the weights arrive. Unknown or unsuitable
hardware must not receive a recommended/installable badge. A successful transfer
alone never establishes that the model is usable on this station.

Use live native telemetry, installed runtime/platform capability and free space
on the actual application backing volume. Never assume a GPU count or pool two
GPUs unless the chosen adapter supports that exact sharding strategy.

For the existing equal-layer CUDA launch (`--tensor-split 1,1,...`), the
single-file estimate limits every share to the smallest selected device after
headroom. A 16-GiB + 8-GiB pair is not interchangeable with 12-GiB + 12-GiB.
Duplicate device observations cannot create artificial capacity. Complete GGUF
bundles additionally use their native largest-layer/shared-tensor proof.

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
- An accepted plan is not permanent hardware authority: recheck capacity before
  downloading its prerequisite engine/companions as well as its selected weights.
  A changed or missing GPU/RAM profile must stop transfer and request a new review.
- No implicit CPU/RAM offload, swap, cloud substitution, eviction of external
  processes or driver modification. Any CPU/offload option is explicit.
- Estimates are not benchmarks. Actual first-result qualification can promote an
  exact model/runtime/workload/hardware observation; never predict token/s or
  film quality from a download count. Failed loading retains the installed object
  and actionable diagnostics rather than selecting another model invisibly.

## Discovery ranking

An explicit comparison checks the top three results of a saved search.
One private inspection Run reads bounded public metadata/configurations, reuses
one hardware/storage observation and assesses all admitted variants locally; it
downloads no weights and starts no runtime. Keep partial source failures visible
per repository rather than recommending them. Rank supported workload fit, useful
context and already present verified objects before transfer cost/popularity;
this is suitability, not a model-quality or speed benchmark.

Each successfully inspected repository keeps its immutable hashed observation
inside the comparison. Opening a result shows that same source/variant review;
installation planning accepts only a matching nested observation from the owned
completed comparison. It must not silently resolve a moving publisher branch
again. The existing plan/license/download path, Stop/claim/administrator fences
and private history remain authoritative. Normal tests cover partial failures,
unknown hardware, ranking, nested-observation tampering and account boundaries;
desktop/mobile/keyboard checks cover comparison progress and returning to results.

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

## Implementation tracking

- Source/search/hardware-review UI and private inspection lifecycle: merged in
  PR #645. Its unused test-parameter TypeScript correction is included in the
  subsequent installation branch; runtime build/component checks were distinct.
- New single-file GGUF plan/install/adopt/Chat route: merged in PR #646, including
  the TypeScript correction, native disagreement and Stop/Resume tests. Real isolated
  Docker/native/GPU qualification downloaded a new 491 MB Qwen2.5 0.5B object and
  received its first reply; the owned test runtime is stopped. See `docs/models.md`.
- Repository variant advice: the supported publisher configuration is resolved
  once, shared across immutable file variants and reused by installation plans.
  A 32K balanced target compares useful fitted context, known quantization and
  GPU count; explicit 128K plans preserve their target and trained limit. Unknown
  sensors/storage and low-bit precision tradeoffs are shown separately. Local
  validation and browser evidence accompany the implementation PR.
- Native media admission primitive: a fixed Qwen2.1 checkpoint profile shares the
  bounded GGUF reader with existing LLM inspection, validates the full graph and
  payload layout, and binds its reference to the exact runtime recipe. Tiny fake
  headers and read-only actual reference/different-graph checks cover it. This is
  structural inspection only; new media installation and runtime use remain open.
- New Qwen Image 2.1 image checkpoint path: publisher geometry and native slot
  snapshots feed the existing resumable downloader, an optional fixed engine
  prerequisite and shared image registration. Workspace/assistant choices freeze
  the owned diffusion source with fixed companions. Native dispatch checks graph
  and component budgets; unit/fake integration tests cover Generate/Edit/Recompose,
  Stop/Resume, cleanup uncertainty and account privacy. An isolated real Q4_0
  installation completed Generate, Edit and two-reference Recompose on Linux;
  owned jobs and Runner are stopped. Local validation passed 439 selected Python
  regressions, global lint/format, 43 frontend tests, frontend lint/typecheck/build
  and desktop/mobile browser checks; the Docker image also built successfully.
  Other image architectures and all remaining media families still
  require their own compatible slots.
- Native video admission: bounded SafeTensors descriptors and a fixed Wan 2.2 5B
  diffusion slot verify tensor names/shapes, F16 storage and complete nonoverlapping
  payload coverage without loading weights or code. The slot binds the exact
  existing engine and companion recipe; the typed verification operation requires
  immutable app-owned storage and model/read permissions. Read-only reference hash
  and structural evidence are recorded privately. Discovery/install/selectors and
  first-result qualification are connected in the video installation path below.
- Still required: cross-model hardware-ranked discovery,
  complete split/companion plans, validated multimodal model slots and selectors,
  install/update/removal UX and release QA/packages. These remain part of the
  requested release; a successful single-file language-model flow is not completion.

Video installation and selection: a new single-file F16 Wan 2.2 5B plan binds
its actual immutable header and the full native engine/companion recipe.
A missing model card does not block a file with a supported verified graph.
It uses the existing model downloader with an optional owned video-setup
prerequisite, explicit license and CPU-offload workload acceptance, native graph
admission and shared definitions with private history. Explicit Video/film/agent
selection freezes the owned checkpoint and original opaque engine identity;
only the diffusion source may change. Existing configured paths and saved legacy
requests retain priority unless a new model is explicitly selected. Readiness
and dispatch must recheck each selected GPU, physical RAM, user memory scope and
unchanged checkpoint. Local source/install/process/agent/film regressions,
frontend checks and desktop/mobile browser qualification passed. An isolated real
Docker/native import of a public mirror of existing reference weights completed
GPU Generate (17 frames, 1280×704, 20 steps); all frames decoded and owned processes
are stopped. This qualifies that Linux path, not a new trained model, full fresh
download, other precisions or Windows GPU execution. See `docs/models.md`.

Next: extend compatible media recipe slots, preserving exact companion/runtime
identities and native verification. Cross-model recommendations and complete
bundle plans remain required. Popularity is not quality or hardware compatibility;
never label an unmeasured choice the fastest/best. Unknown media/companion families
retain their actual missing-recipe reason.

Agent-definition routing increment: give the queued local draft generator bounded
registered image/video choices and their actual adapter/workload constraints.
Validate IDs against the supplied catalog and current registry before publishing
a disabled definition. Names are untrusted reference data; no paths, model setup
permissions or download URLs enter this catalog. Runtime and hardware validation
still happen at reviewed activation/execution. This does not complete automatic
selection in every direct-chat media path or add the remaining media families.


Speech checkpoint increment: add a bounded F32 Chatterbox multilingual v3 T3
SafeTensors slot, derived from the immutable publisher header, bound to the
complete existing speech recipe and its exact tokenizer/voice encoder/decoder/
conditional companions. Only an immutable owned object with model/read permission
may request this structural inspection. The slot grants no arbitrary model role,
Python/pickle loading, runtime installation or generation. Connect reviewed source
plans, complete preparation, runtime binding/selectors and first-result execution
in the following increment; until then new speech checkpoints remain unavailable
for operational use. Other Chatterbox versions/precisions and Fish bundles need
separate compatible slots; never infer compatibility from a model name.


### Connecting installed speech checkpoints

Implemented in the speech installation increment: the source/plan/downloader,
opaque engine binding, native execution and Audio/agent/explicit-conversation
choices below share existing lifecycle services. Hardware, publication, recovery
and UI regressions passed; isolated actual source/setup/GPU speech and owned cleanup
also passed on Linux. See [measured evidence and scope](../models.md#discovered-speech-models).
Other speech formats, avatar voice stages and automatic routing still require
their own admission work; this increment does not complete the release goal.

1. Extend the existing Chatterbox environment resolver with a frozen opaque
   identity, as for video. Shared readiness and execution must not expose the
   preparing account's Run ID or accept paths/commands from clients. Explicit
   selection can use that prepared engine while legacy configured speech keeps
   its current priority for requests without a model choice.
2. Plan one publisher T3 file against the native slot, immutable header/full-file
   identity and complete existing engine manifest. Review all companion/SDK
   licenses and the actual workstation's GPU, RAM and backing-volume budget
   before transfer. Fixed F32 is the only admitted precision initially; file size
   alone does not prove fit. Reuse the existing model Task/downloader with a
   narrowly authorized `speech_setup` prerequisite, not a second install queue.
3. After full download verification and native graph/header recheck, publish an
   audio-category definition with a speech binding, private preparation history
   and no changed default. Stop, administrator revocation or source changes must
   prevent publication. Re-check must use the existing object rather than start
   another download.
4. Freeze explicit model and opaque engine in ordinary speech Runs. The native
   parent and offline child check the owned T3 graph/content and original engine;
   a run-owned model view can replace only the T3 coordinate. The tokenizer,
   decoder, voice encoder, conditionals and prepared SDK stay fixed. Preserve
   original process ownership, bounded memory scope, deadline, offline behavior,
   reference validation, chunking and cancellation/recovery. No new arbitrary
   Python, shell, model-directory or runtime controls.
5. Share the installed choice between Audio, reviewed agents and applicable
   conversation settings. Fish remains a separate engine; a Chatterbox model ID
   must never be silently ignored on a Fish request. Saved scopes retain their
   model and runtime through execution. The draft catalog describes registered
   choices, not proof of live runtime health.
6. Cover source/install/publication fences, default compatibility, agent/chat
   scopes, process Stop/recovery and desktop/mobile interaction with fake inputs.
   Then opt into one isolated real source/import/GPU speech result and validate
   its audio and cleanup. Distinguish reused reference weights or descriptor
   fixtures from a newly trained model and a real-weight generation test.

### Next: discovered memory encoder bundles

Preserve the existing CPU ONNX E5 encoder and advanced compatible endpoint. This
family should extend that bounded worker-side CPU service, not launch or evict a
chat GPU runtime. Before admitting a new encoder:

1. Inspect the existing `embedding_models`, `embedding_cpu`, `embedding_process`,
   preparation/settings revision and vector-identity contracts. Pick one explicit
   compatible E5 export profile; do not claim universal ONNX support or confuse a
   generative/vision model with a retrieval encoder.
2. Freeze the publisher configuration, model file and tokenizer as a complete
   immutable bundle. Source metadata provides a conservative CPU/RAM/disk estimate
   before transfer; unknown architecture or tokenizer relationships remain
   unsupported. Reuse model Tasks, consent, the object store and verified downloads.
3. After download, inspect the graph in a bounded offline owned CPU child before
   registry publication. Forbid external tensor data, custom operators/libraries,
   remote code and arbitrary paths. Check the admitted inputs/outputs, dimensions
   and tokenizer contract. Add a pinned parser dependency only after checking the
   existing image/dependencies; never install packages from a model repository.
4. Register a shared model binding and expose an explicit **Use for memory**
   action. Installation alone must not change the machine's encoder or endpoint.
   Freeze model/bundle/encoding identity in each health/index/search Run; selecting
   another encoder invalidates incompatible vectors through existing revisions.
   Preserve private account indexing/history and shared-model visibility.
5. Preserve CPU thread/address-space limits, parent-death/Stop/recovery, scoped
   retrieval and FTS during setup/failure. Larger or different exports require
   their own measured profile; never silently increase the heap or use a GPU.
6. Qualify one public compatible export through source → complete bundle →
   explicit selection → actual nonzero vectors and Polish semantic retrieval.
   Fake tests cover source/hash/tokenizer/graph drift, settings races and account
   boundaries; browser checks cover install/selection and indexing progress.

### Next: ACE-Step music checkpoint bundles

Delivered on develop in #657/#658: bounded native graph admission, licensed
complete installation, opaque engine bindings and explicit Music/agent/chat
selection. The isolated reference import produced a fully validated 10-second
WAV; see `docs/models.md`. Other music architectures still require their own
profiles. This does not complete the cross-capability discovery release.

1. Establish one metadata-only native slot for the complete existing ACE-Step
   1.5 Turbo diffusion graph, using the bounded SafeTensors reader. Freeze its
   exact graph/storage precision, existing runtime recipe, SDK, configuration,
   tokenizer/embedding model, VAE and pinned model Python companions. Model
   publisher Python is never new execution authority. Matching a header alone
   does not install or qualify a music model.
2. Extend existing discovery/download Tasks with that finite slot and complete
   companion/engine consent and storage estimate. Recheck the real music workload:
   one supported 12-GiB GPU, at least 24-GiB RAM and its explicit CPU-offload
   policy. Two cards do not make a single-device memory requirement disappear.
3. Bind a verified owned checkpoint to an opaque prepared music engine, replacing
   only the diffusion object in a private Run view. Keep the existing source/code
   hashes, deadlines, memory scopes, owned process Stop and inspection recovery.
   A generic model filename or a new repository's Python must not bypass them.
4. Expose installed choices in Music and reviewed conversation/agent settings,
   preserving explicit existing defaults. Qualify download/adoption/selection,
   source/hash/graph drift, permissions and cancellation with fake executors, then
   an isolated actual GPU music result. Update qualification evidence honestly;
   a metadata slot is only the first implementation step.

### Sonic avatar checkpoint bundles

The native structural slot and closed data reader are implemented on the
development branch. The real pinned reference passed read-only layout inspection
and all-tensor CPU equivalence against the trusted legacy load, without GPU
initialization. Normal tests exercise malformed/executable metadata, owned paths,
graph/companion drift and per-device GPU/RAM/driver/disk gates. These structural checks are the initial admission stage; complete source
installation and selected inference are qualified below.
Publisher inspection also passed on the immutable official file using six
metadata-only ranges (480,930 bytes), with the same graph/version/header
fingerprints. It uses the existing public pinned HTTPS transport and cannot read
tensor storage or claim native layout validity. Source-plan/installation wiring
and selected-model inference are connected and qualified below.

The Linux import now connects closed tensor source inspection, complete hardware,
license/offload review, ordinary downloads/preparation and shared model definitions.
Avatars, reviewed agents and explicit conversation tools can choose the installed
model. Plans retain that exact source and engine across speech handoff, retries
and resume; model renames/default changes cannot retarget an existing operation.
Version-2 native receipts carry the selected checkpoint; legacy receipts remain
unchanged. Initial engine hashes defer the same Run without duplicate transfer,
and verified cache reuse preserves native file identity.

Qualification completed on 2026-11-05 using the pinned official reference source,
92 complete engine inputs and an ordinary selected-model avatar Run on one
12-GiB RTX 3060. Its full two-second recording produced 50 frames at 512×768/25fps
with verified audio and exact checkpoint identity. Source/registration, Stop and
native cleanup were inspected. The Run took 11m49s including native verification
and generation; this one-card profile fits but is expensive. The existing two-GPU
guidance remains supported and unit-tested; this new selected-source smoke used
one card. Compiled source/review/consent/selection/refresh/keyboard checks passed
at desktop and phone widths. These browser checks replay real API projections
with controlled responses, separately from actual GPU qualification.

This proves the import route for the fixed Sonic graph and its data-only format,
not arbitrary PyTorch files, a newly trained model's face quality, all recording
lengths or Windows GPU behavior. The development feature is not in published
0.1.2 installers. Further families, complete shard admission, lifecycle/QA and
release packaging remain part of the open discovery goal.

1. Inspect the actual Sonic loading path before choosing a replaceable role.
   Current inference builds the adapted UNet from SVD configuration but loads
   `Sonic/unet.pth`, including its identity/attention adapters. An SVD UNet file
   that inference never reads is not a working avatar import.
2. The actual publisher checkpoint is an uncompressed PyTorch ZIP state dict.
   First qualify a closed data-only decoder for its finite wire format: bounded
   ZIP directory/local records, primitive metadata and tensor/storage descriptors.
   Use `pickletools` only for opcode inspection; never call pickle loading,
   publisher globals, reducers, constructors or `torch.load` on new weights.
   Symbolic reconstruction may recognize only the fixed plain dictionary/tensor
   forms and must reject executable/unknown instructions, aliases, arbitrary
   strides, compressed/external entries, invalid spans and unbounded inputs.
   Inference can map verified raw storage into CPU tensors without unpickling.
   Keep legacy trusted inputs separate. Qualify the exact complete Sonic graph,
   precision, module-version metadata and original companion recipe; a generic
   PyTorch archive is not a supported model. SafeTensors can be a subsequent
   serialization of the same qualified graph rather than a substitute for the
   actual published format.
3. Bind the fixed Sonic runtime, audio-to-token/bucket, portrait/voice encoders,
   VAE, scheduler/configuration and all other companions. New source model Python,
   arbitrary workflows or a filename must not change the trusted inference path.
   Qualify the actual selected safe export loader rather than assuming a different
   serialization is interchangeable.
4. Reuse the model Task/download/prerequisite lifecycle and opaque runtime
   identities. Estimate its real one-/multi-device workload, per-device memory,
   physical RAM, complete storage and any explicit offload policy before transfer.
   Preserve whole-audio/windowed execution, private input lineage, absolute
   deadlines, owned cancellation and inspection recovery.
5. Expose the installed choice in Avatars and applicable reviewed agent/chat
   settings. A known reference converted to a newly supported serialization proves
   that route, not a new trained model's quality. Test fake admission/ownership/
   hardware boundaries, then complete an isolated actual selected-model avatar
   result and inspect video/audio integrity before enabling that profile.

The data-format work follows the official
[PyTorch archive contract](https://docs.pytorch.org/docs/stable/notes/serialization.html#serialized-file-format-for-torch-save)
and Python's [non-executing pickle inspection tools](https://docs.python.org/3/library/pickletools.html).
Those references describe formats; they do not grant arbitrary model code authority.

### Next: complete split-GGUF hardware advice and execution

Single-file language candidates already reject projector files and conventional
`00001-of-00002.gguf` fragments. Keep that refusal until the entire runtime path
accepts a complete bundle. Current source inspection filters a pasted file link
before retaining its siblings, so it cannot yet explain the complete split model's
size. An individual fragment's bytes must never become the whole-model estimate.

1. Extend the immutable publisher observation with a bounded declared part set.
   Resolve sibling names/hashes/sizes from that same pinned revision even when
   the user pasted one part's link. Separate directories and quantization groups;
   reject duplicates, mismatched numbering/counts and incomplete/unknown identities.
   Report the complete declared byte total only when every required part is known.
   Filename grouping is publisher metadata, not verified GGUF tensor admission.
2. Show one model/bundle review with its required parts, full disk requirement and
   clear missing/unsupported state. Preserve existing single-file behavior and
   keep fragment installation unavailable until bundle execution is qualified.
   Hardware advice must include all weights, context/KV geometry, runtime,
   companions and installed-storage reserve; no arbitrary pooling of GPU memory.
3. Add a typed native bundle coordinate and bounded cross-part GGUF inspection:
   consistent split metadata, complete tensor inventory/layout, exact file
   observations and content hashes. Reuse the existing llama.cpp resource fitter.
   Native launch mounts only those verified objects under fixed server-generated
   part names; publisher filenames must not become Docker mount options or shell
   arguments. Freeze the aggregate identity in ownership/recovery receipts while
   legacy single-file payloads retain their current serialization.
4. Compose all-part download/adoption inside the ordinary model Task, with one
   owner, license review, Stop fence and registry publication only after complete
   native admission. Context changes, Chat, agents, inspection, cancellation and
   recovery must retain the same complete bundle instead of reopening a first
   shard against a moving/default directory.
5. Test complete/missing/mixed parts, a pasted non-first part, insufficient total
   disk/VRAM/RAM, unsupported runtime, cancellation and changed observations before
   registration. Qualify an actual small complete split fixture using a pinned
   trusted splitter over a private copy of known reference weights; keep original
   model files untouched. A format conversion can qualify the loading route, not
   a different training's quality. Follow with the release QA/package matrix.

Delivery can separate complete metadata/hardware explanation from native bundle
activation, but an unfinished group must stay explicitly unavailable. Do not
claim split-model installation from an inspection or a small fragment alone.

#### Split-model metadata stage

The source/UI stage now retains complete declared groups from the same revision,
including a pasted second-part link. A shared bounded manifest records required
files and identities; separate directories/quantizations do not merge. Missing,
conflicting, duplicate-object or unverifiable sets retain unknown total size.
The source review presents one bundle and its full weight-storage requirement,
with optional part details. Older fragment observations keep their installation
refusal. Context/native residency and complete-bundle execution remain unqualified;
metadata completeness must not become a GPU-fit or installation recommendation.

On 2026-11-05, a public pinned Qwen2.5-72B GGUF source returned a two-part set
of 50.71 GiB even when inspected through its second file's link. Only bounded
publisher metadata was read. Fake API tests cover durable observation publication,
aggregate disk refusal, private report artifacts and rejection of a fragment plan
without creating model records. This is source/hardware explanation, not a split
model download or inference qualification; steps 3–5 above remain required.

Native format references for the next step: the upstream splitter stores full
model metadata in the first part, writes `split.no` and `split.count` as unsigned
16-bit values, and `split.tensors.count` as signed 32-bit. It can intentionally
create a first part without tensors. Later parts must therefore not be required
to repeat the first part's architecture/context fields.
[Splitter implementation](https://github.com/ggml-org/llama.cpp/blob/master/tools/gguf-split/gguf-split.cpp),
[metadata key definitions](https://github.com/ggml-org/llama.cpp/blob/master/src/llama-arch.cpp).
These document the format; qualification must still use a pinned trusted SDK.


### Native complete GGUF admission — 2026-11-05

The typed native verifier and Linux llama.cpp loader now accept frozen complete
owned part sets. All split wire types, zero-based positions/counts, bounded global
tensor inventories, unique names, quantized-row/storage extents and repeated
geometry are checked. Full context comes from the first file; a metadata-only
first part is valid. Single-file loading refuses actual split metadata even after
renaming. Existing single-file request/receipt serialization remains unchanged.

The whole-set size drives per-device admission, with a conservative full Q8 cache
on each GPU, equal-layer rounding/shared tensor allowance and runtime margin.
Available RAM is checked separately. Missing sensors, an individually insufficient
GPU, unsupported context, incomplete/changed sources or a different runtime image
refuse dispatch. Mounts use canonical server names and read-only individual files;
replay/recovery and Stop preserve exact container ownership even after source loss.

Qualification used the already downloaded, checksum-verified public Qwen2.5 0.5B
Q4_K_M fixture, split locally by llama.cpp source revision
`aa39d7a3e145a88202793a89462d65e94a5fc25f`. Its original file was unchanged.
The pinned CUDA image `95cdc1510dbc…` returned `split model works.` on two RTX 3060
12 GB devices from both a two-part ordinary set (491,400,256 bytes, 291 tensors)
and a three-part zero-tensor-first set (491,400,384 bytes). The ordinary set
survived a real Runner restart with the same container; both sets stopped after
one original source disappeared. All owned test containers/Runner are closed.
This qualifies the native bundle path for that fixture/image on Linux, not all
model architectures or Windows GPU execution. No new publisher weights or media
were downloaded/published in this qualification.

The following source-installation qualification completes whole-part transfer,
registry binding and ordinary Chat/agent selection. Native structural success
alone never enables a source recommendation; lifecycle, QA, documentation/site
and packaged Linux/Windows release gates remain required.


### Complete source installation — qualified Linux path, 2026-11-05

The control plane freezes every part and its pinned common configuration while
preserving the primary ModelFile's physical size. Plans, storage headroom,
progress and resumable transfers account for the complete set. Registration
requires matching native whole-set and attention/cache geometry. The shared model
binding follows ordinary Chat, agent selection, runtime source/handoff and
ownership facts; GPU and host-RAM reservations survive readiness and release only
after confirmed Stop. The Models and discovery UI show complete size, part count
and component details. Old fragment-only observations do not gain admission.

The source-installation gate is now enabled after these distinct checks:

- The controlled publisher/HTTP fixture streamed actual previously verified
  Qwen2.5 0.5B weights through the real downloader. A deliberate second-part
  interruption resumed from byte 1,048,576 without retransferring the first part.
  Hash verification, native inspection, registration, ordinary GPU Chat and Stop
  all passed in an isolated hardened control-plane container/native Runner. This
  is controlled transport evidence, not a public Hugging Face multipart transfer.
- A real public pinned second-file link from
  `Qwen/Qwen2.5-7B-Instruct-GGUF`, revision
  `bb5d59e06d9551d752d08b292a50eb208b07ab1f`, downloaded both Q4_0 files:
  3,983,228,352 and 448,162,496 bytes (4,431,390,848 total). The initial native
  inspection exposed a context-policy mismatch: the publisher config declares
  32,768 while the GGUF declares 131,072 tokens. After fixing that policy, the
  same Task resumed from its verified cached files, registered one model, returned
  `4` in ordinary Chat and completed a manual agent on the same single runtime.
  The default remained the reviewed 32K/Q8 preset on one RTX 3060 12 GB. Stop
  removed that exact container and released every GPU/RAM reservation.
- Attention architecture/layer/cache/state dimensions and source identities must
  still agree exactly. A differing file context is accepted only if it covers
  the reviewed limit (the fixed CPU profile reviews 4096). It is retained as
  native evidence, logged and explained in model details; installation does not
  silently enlarge the preset. A smaller-than-reviewed file limit still refuses
  registration. Header context is an advertised limit, not model-quality proof.
- Temporary-database/native-metadata tests also cover missing/incorrect parts,
  whole-set hashing identity, sourcepart2 planning, failed-part resume, Stop before
  registration, shared-runtime scalar timestamp precision, normal Chat dispatch,
  retained RAM and confirmed resource release. Compiled desktop/mobile checks use
  the retained actual source/plan/model snapshots; screenshots remain private.

The public transfer, controlled interruption and actual GPU inference are separate
claims. Production data and external services were untouched. These checks do not
qualify Windows GPU hardware, every architecture or every advertised context.
Finish complete lifecycle/ranking, operator QA/workbook, README/site, packaged
Linux/Windows regression and owner-reviewed release promotion before closing the
full discovery goal.


Logical identity and lifecycle across shared GGUF components are implemented
below. Release review must retain evidence for independent selections, legacy
references, migration, source aliases, removal/restore and account/runtime
ownership. Shared weights must never be copied or an existing definition overwritten.


Logical selection implementation: retain existing `llamacpp:<file UUID>` references
for each primary/default definition. Additional complete GGUF sets sharing that
physical file use `llamacpp:<definition UUID>` and a unique ordered SHA/size content
key, excluding mutable timestamps and publisher aliases. A partial unique index
retains one default definition per file. Typed loading freezes the optional
logical definition ID alongside the complete binding; context history, runtime
reuse, reasoning, handoff and agent routing must never confuse sibling sets.
No duplicate file rows or copied shared weights are introduced. Migration downgrade
must refuse while additional bindings exist rather than discard model choices.


The logical-binding candidate also retains removed complete-model definitions as
identity tombstones. Removal is refused while that logical runtime is active or
uncertain; it hides the choice without deleting cached weights or capturing old
conversation references with a sibling model. Explicit native re-verification or
reviewed installation restores the same choice. Sibling models keep their own
presets, parts, reasoning qualification and runtime history. Operator UI selects
configurations explicitly, preserves that selection on refresh and never carries
an unsaved preset into another configuration. Qualification remains recorded in
the implementation/review evidence; this is not yet a packaged release.


Publisher lifecycle: definitions expose a narrow canonical public source record,
not their private download Run or complete recipe. Existing media source snapshots
and new language/split installs share this projection. Known older curated files
may use an exact SHA/size catalog match; unknown origins stay unknown. Opening
"Review publisher updates" pre-fills the existing discovery input. It performs
no automatic source request, transfer, runtime change or default replacement;
new metadata and installation still require the ordinary reviewed Task/Run flow.


Cache-aware advice uses only prior shared owned-object observations and bounded
read-only filesystem metadata, through directory descriptors without following
symlinks. Complete GGUF proofs contribute every part; unregistered, missing,
changed, linked or writable objects do not reduce the estimate. The UI separates
whole-model size, reusable weights, estimated model transfer and additional disk
reserve. Runtime/companion/staging allowances and hardware fit are preserved.
Metadata matching is advisory, not a fresh content proof: even an object whose
stat fields were maliciously restored is rehashed by the downloader before native
verification/use. Ranking never upgrades unsupported hardware/runtime because a
file is cached. New plans recompute observations; saved hints grant no authority.
