"""Transparent local-only selection from installed, observed long-context GGUFs."""

from sqlalchemy import select

from app.llama import fit_coding_context, loadable_model
from app.models import ModelFile, Run, RuntimeInstance
from app.providers import ProviderError
from app.runner_client import RunnerClient

MINIMUM_CONTEXT = 100352  # First supported 256-token allocation above 100k.


def observed_context(instance):
    metadata = instance.metadata_json
    observation = metadata.get("observation")
    requested = metadata.get("context_size")
    actual = observation.get("n_ctx") if isinstance(observation, dict) else None
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
        rid: (created, status)
        for rid, created, status in session.execute(
            select(Run.id, Run.created_at, Run.status).where(Run.id.in_(load_ids))
        )
    }
    loaded_at = {rid: values[0] for rid, values in loads.items()}
    candidates = []
    for model in session.scalars(
        select(ModelFile).where(
            ModelFile.category == "llm", ModelFile.availability == "present", ModelFile.format == "gguf"
        )
    ):
        if not loadable_model(model):
            continue
        observations = [
            i
            for i in history
            if i.metadata_json.get("model_file_id") == model.id
            and i.metadata_json.get("model_size_bytes") == model.size_bytes
            and i.metadata_json.get("model_mtime") == model.mtime
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
                observed_context(i)
                for i in matching
                if i.status in {"ready", "stopped"}
                and i.metadata_json.get("cache_type") == "q8_0"
                and i.metadata_json.get("context_fit") == "ok"
                and loads.get(i.metadata_json.get("load_run_id"), (None, None))[1] == "succeeded"
            ]
            or [0]
        )
        failed = [
            int(i.metadata_json.get("failed_context_size", 0))
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
