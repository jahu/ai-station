# Model file discovery

The Models workspace lists external files from the Host Runner's configured `AI_STATION_MODEL_ROOTS`. `POST /api/models/discover` only enqueues a Task/Run. The worker dispatches the typed `/v1/runs/model-scan` endpoint with `filesystem_read` and `manage_models` permissions; callers cannot supply paths, commands or output locations. The runner owns a separate process group and applies the same durable identity, byte-offset logs, cancellation and conservative recovery rules as other native work.

Discovery uses descriptor-relative metadata inspection, does not open model contents, skips symlink files/directories and non-regular files, and rejects traversal into a different filesystem. Mount roots can be configured explicitly. It is bounded to 100,000 traversed entries, 5,000 models and a 60-second traversal budget. Filesystem calls blocked in the kernel can exceed the traversal budget; owned-process cancellation remains available. Models are never loaded, moved, renamed, deleted, copied or downloaded. UUID report paths remain under app-owned artifact storage and reject symlink redirection. The previous synchronous scan endpoint is no longer operational.

A known successful process exit and validated report are required before the worker updates the registry. The JSON inventory becomes a normal artifact. Partial scans, errors and cancellation do not overwrite the previous registry. Each file retains a stable ID, first-discovered timestamp, last-seen timestamp, latest observation Run and status:

- `present`: found in the completed scan; this is an observation, not a live loaded state.
- `missing`: not found under a root that completed its scan.
- `unknown`: the root was unavailable or is no longer configured.

Removed external files remain visible for inspection; no destructive endpoint is exposed. Search is literal filename matching, and category filters/pagination run in SQL. Categories, family, quantization and capability hints are inferred from configured root/filename conventions and are labelled as hints, not verified runtime compatibility.

Model File, Model Definition, Runtime and Runtime Instance remain separate records. Discovery creates Model File observations only. It does not invent curated model definitions or claim existing runtimes are managed. Runtime controls/registry UI are still pending; actual diagnostic checks remain available in System.

Migration `0002` adds nullable observation timestamps/Run links and an `unknown` default for pre-existing rows. Upgrade/downgrade coverage verifies existing file metadata survives. Tests use disposable small fixtures, real managed subprocesses and an in-process typed runner transport. The browser smoke uses a native runner over UDS and a worker. Neither test loads model weights.
