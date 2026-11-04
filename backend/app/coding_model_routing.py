"""Transparent local-only selection from installed, observed long-context GGUFs."""

from sqlalchemy import select

from app.llama import fit_coding_context, loadable_model
from app.models import ModelFile, Run, RunEvent, RuntimeInstance
from app.providers import ProviderError
from app.runner_client import RunnerClient

MINIMUM_CONTEXT = 100352  # First supported 256-token allocation above 100k.


def observed_context(instance, loaded=None):
    metadata = instance.metadata_json
    observation = metadata.get("observation")
    requested = metadata.get("context_size")
    actual = observation.get("n_ctx") if isinstance(observation, dict) else None
    # A stop observation describes process liveness and may omit n_ctx. The
    # successful load's persisted native measurement remains allocation proof;
    # requested settings or another instance's event never substitute for it.
    if (
        actual is None
        and instance.status == "stopped"
        and isinstance(loaded, dict)
        and loaded.get("instance_id") == instance.id
        and loaded.get("gpus") == metadata.get("gpus")
        and loaded.get("cache_type") == metadata.get("cache_type") == "q8_0"
    ):
        actual = loaded.get("n_ctx")
    if type(requested) is not int or type(actual) is not int or min(requested, actual) <= 0:
        return 0
    return min(requested, actual)


def select_coding_model(session):
    try:
        devices = RunnerClient().hardware().get("gpus", [])
        memory = {int(g["index"]): float(g["memory_total_mib"]) for g in devices}
    except Exception as exc:
        raise ProviderError("Inspect Host Runner GPU discovery before choosing Auto coding") from exc
    history = list(session.scalars(select(RuntimeInstance).where(RuntimeInstance.ownership == "managed")))
    load_ids = [i.metadata_json.get("load_run_id") for i in history if i.metadata_json.get("load_run_id")]
    loads = {
        rid: (created, status, parameters, executor)
        for rid, created, status, parameters, executor in session.execute(
            select(Run.id, Run.created_at, Run.status, Run.parameters, Run.executor_type).where(
                Run.id.in_(load_ids)
            )
        )
    }
    load_observations = {}
    for rid, payload in session.execute(
        select(RunEvent.run_id, RunEvent.payload)
        .where(RunEvent.run_id.in_(load_ids), RunEvent.event_type == "runtime.ready")
        .order_by(RunEvent.sequence.desc())
    ):
        load_observations.setdefault(rid, payload)
    # The model is shared, while its initiating Run and event stream are private.
    # Project only source/device/context facts; never broaden the ORM data scope.
    from app.data_access import ScopedSession
    from app.runtime_coordination import runtime_coding_facts

    if isinstance(session, ScopedSession):
        for instance in history:
            loader_id = instance.metadata_json.get("load_run_id")
            if loader_id is None or loader_id in loads and loads[loader_id][1] == "succeeded":
                continue
            try:
                facts = runtime_coding_facts(session, instance)
            except ValueError:
                continue
            loads[loader_id] = (
                facts["created_at"],
                "succeeded" if facts["retained"] else facts["status"],
                {"instance_id": instance.id, "gpus": facts["gpus"], **facts["source"]},
                "llama_load",
            )
            load_observations[loader_id] = facts["ready_observation"]
    loaded_at = {rid: values[0] for rid, values in loads.items()}
    candidates = []
    for model in session.scalars(
        select(ModelFile).where(
            ModelFile.category == "llm", ModelFile.availability == "present", ModelFile.format == "gguf"
        )
    ):
        if not loadable_model(model):
            continue

        def matches_file(instance):
            if instance.runtime_key != "llama.cpp":
                return False
            meta = instance.metadata_json
            if meta.get("model_size_bytes") == model.size_bytes and meta.get("model_mtime") == model.mtime:
                return True
            load = loads.get(meta.get("load_run_id"))
            if load is None or load[1] != "succeeded" or load[3] != "llama_load":
                return False
            params = load[2]
            return (
                params.get("instance_id") == instance.id
                and params.get("gpus") == meta.get("gpus")
                and params.get("model_path") == (model.relative_path or model.host_path)
                and bool(params.get("app_owned")) == bool(model.relative_path)
                and params.get("size_bytes") == model.size_bytes
                and params.get("mtime") == model.mtime
            )

        observations = [
            i for i in history if i.metadata_json.get("model_file_id") == model.id and matches_file(i)
        ]
        if any(i.status == "unknown" for i in observations):
            continue
        prior = [i for i in history if i.metadata_json.get("model_file_id") == model.id]
        prior.sort(
            key=lambda i: (
                loaded_at.get(i.metadata_json.get("load_run_id"), i.updated_at),
                i.id,
            ),
            reverse=True,
        )
        source = next(
            (i for i in prior if i.status in {"ready", "queued", "loading"}), prior[0] if prior else None
        )
        if source not in observations:
            continue
        gpus = source.metadata_json.get("gpus", [])
        if not gpus or any(index not in memory for index in gpus):
            continue
        matching = [i for i in observations if i.metadata_json.get("gpus") == gpus]
        profiles = [
            i.metadata_json["context_profile"] for i in matching if i.metadata_json.get("context_profile")
        ]
        if not profiles:
            continue  # Unknown trained context is never advertised as a 100k model.
        profile = profiles[0]
        proven = max(
            [
                observed_context(i, load_observations.get(i.metadata_json.get("load_run_id")))
                for i in matching
                if i.status in {"ready", "stopped"}
                and i.metadata_json.get("cache_type") == "q8_0"
                and i.metadata_json.get("context_fit") == "ok"
                and loads.get(i.metadata_json.get("load_run_id"), (None, None))[1] == "succeeded"
            ]
            or [0]
        )
        failed = [
            int(i.metadata_json.get("failed_context_size") or i.metadata_json.get("context_size", 0))
            for i in matching
            if i.metadata_json.get("context_fit") == "too_large"
        ]
        context = fit_coding_context(
            gpus=gpus,
            size_bytes=model.size_bytes,
            gpu_memory_mib=[memory[index] for index in gpus],
            proven_success=proven,
            failed_sizes=failed,
            context_profile=profile,
        )
        if context < MINIMUM_CONTEXT:
            continue
        # A slightly larger estimate is not worth discarding an already proven
        # usable allocation. Requested settings alone never prove runtime size.
        if proven >= MINIMUM_CONTEXT:
            context = min(context, proven)
        verified = proven >= context
        candidates.append(
            (
                verified,
                "coder" in model.filename.lower(),
                model.size_bytes,
                context,
                model.id,
                {
                    "model": "llamacpp:" + model.id,
                    "name": model.filename,
                    "context_size": context,
                    "context_verified": verified,
                    "gpus": gpus,
                    "reason": "Installed local GGUF with observed trained context; "
                    + (
                        "this context has already loaded successfully."
                        if verified
                        else "allocation is estimated and checked again during loading."
                    ),
                },
            )
        )
    if not candidates:
        raise ProviderError(
            "Auto coding needs an installed llama.cpp model with an observed 100k+ context that fits your GPUs. Load/check a long-context GGUF in Models, or explicitly choose a model."
        )
    return max(candidates, key=lambda item: item[:-1])[-1]
