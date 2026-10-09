# Model files, definitions and installation

The Models workspace lists external files from the Host Runner's configured `AI_STATION_MODEL_ROOTS`. Observed files and curated definitions are each one keyboard sequence (arrows, Home, End, Enter inspects) with unique Inspect names; decorative type icons stay out of the tab order. `POST /api/models/discover` only enqueues a Task/Run. The worker dispatches the typed `/v1/runs/model-scan` endpoint with `filesystem_read` and `manage_models` permissions; callers cannot supply paths, commands or output locations. The runner owns a separate process group and applies the same durable identity, byte-offset logs, cancellation and conservative recovery rules as other native work.

Discovery uses descriptor-relative metadata inspection, does not open model contents, skips symlink files/directories and non-regular files, and rejects traversal into a different filesystem. Mount roots can be configured explicitly. It is bounded to 100,000 traversed entries, 5,000 models and a 60-second traversal budget. Filesystem calls blocked in the kernel can exceed the traversal budget; owned-process cancellation remains available. Models are never loaded, moved, renamed, deleted, copied or downloaded. UUID report paths remain under app-owned artifact storage and reject symlink redirection. The previous synchronous scan endpoint is no longer operational.

A known successful process exit and validated report are required before the worker updates the registry. The JSON inventory becomes a normal artifact. Partial scans, errors and cancellation do not overwrite the previous registry. Each file retains a stable ID, first-discovered timestamp, last-seen timestamp, latest observation Run and status:

- `present`: found in the completed scan; this is an observation, not a live loaded state.
- `missing`: not found under a root that completed its scan.
- `unknown`: the root was unavailable or is no longer configured.

Removed external files remain visible for inspection; no destructive endpoint is exposed. Search is literal filename matching, and category filters/pagination run in SQL. Categories, family, quantization and capability hints are inferred from configured root/filename conventions and are labelled as hints, not verified runtime compatibility.

## Definitions, presets and compatibility

Model File, Model Definition, Runtime and Runtime Instance remain separate records. Discovery creates Model File observations only. It does not invent curated model definitions or claim existing runtimes are managed.

A definition is created by an explicit UI/API action from a file observed as `present`. It stores a display name, inherited family/category/capability hints, and a load preset (`gpus`, `context_size`, `cache_type`). One definition is linked to one file. Removing the definition does not delete the file.

`GET /api/models/compatibility` returns declared format/category pairings with a runtime family. Those rows are labels, not a successful load, health probe or proof that weights run on this workstation. GGUF language models (except `mmproj` companions) declare the managed llama.cpp adapter. Other formats stay catalogued until a real adapter exists.

## Explicit installation

`POST /api/models/definitions/{id}/install` enqueues a Task/Run (`models.install`) with `filesystem_read` and `manage_models`. The worker calls the typed Host Runner `/v1/models/verify` endpoint. Callers cannot supply roots, commands, pull flags or output paths. The runner stats the snapshotted path inside configured model roots, rejects symlinks and non-regular files, and does not open model contents.

For GGUF language models it also inspects the administrator-configured llama.cpp image ID. Missing images fail closed. The runner never runs `docker pull`, never copies GGUFs and never starts a runtime. A JSON report becomes a normal artifact. Cancellation, errors and a changed size/mtime leave the definition unregistered (`unverified` or `failed`) and do not rewrite discovery observations. Retry is a new Run.

`POST /api/models/definitions/{id}/load` reuses the existing owned llama.cpp load Run with the saved preset. It requires a successful install and a present loadable GGUF.

Owned llama.cpp health and restart are separate inspectable Runs. Health records process liveness and observed context without signalling external runtimes. Restart unloads an idle owned instance, then loads the saved GPU/context preset. Unknown ownership still requires inspection. System diagnostics remain available for the host.

Migration `0002` adds nullable observation timestamps/Run links and an `unknown` default for pre-existing rows. Migration `0018` adds definition status, verification Run links and timestamps. Upgrade/downgrade coverage verifies existing file metadata survives. Tests use disposable small fixtures, real managed subprocesses and an in-process typed runner transport. The browser smoke uses a native runner over UDS and a worker. Neither test loads model weights or pulls images.
