"""One shared recurrent video definition binds the complete owned engine bundle."""

import math
import re
from copy import deepcopy

from sqlalchemy import select

from app.model_setup import fingerprint
from app.models import ModelDefinition, ModelFile
from app.svi_executor import GEOMETRY, PROFILE, RAM_MIB

CHECKPOINT_PROFILE = "wan22-svi-pro-q4-bundle-v1"
ROLES = frozenset(
    {"wan_high_noise", "wan_low_noise", "svi_high_adapter", "svi_low_adapter", "wan_text_encoder", "wan_vae"}
)


def checked_runtime(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"profile", "manifest_sha256", "environment_id"}
        or value["profile"] != PROFILE
        or any(
            not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key])
            for key in ("manifest_sha256", "environment_id")
        )
    ):
        raise ValueError("The recurrent model requires its exact prepared engine")
    return value


def component(row, role):
    if (
        row is None
        or row.availability != "present"
        or row.category != "video"
        or not isinstance(row.sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", row.sha256)
        or row.relative_path != "models/store/" + row.sha256
        or type(row.size_bytes) is not int
        or row.size_bytes <= 0
        or type(row.mtime) not in {int, float}
        or not math.isfinite(row.mtime)
    ):
        raise ValueError("A recurrent model component is unavailable or changed")
    return {key: getattr(row, key) for key in ("id", "relative_path", "sha256", "size_bytes", "mtime")} | {
        "role": role
    }


def checked_binding(session, primary, binding):
    checked_runtime(binding.get("managed_runtime"))
    values = binding.get("components")
    if (
        binding.get("checkpoint_profile") != CHECKPOINT_PROFILE
        or binding.get("cpu_offload") is not True
        or binding.get("workload_accepted") is not True
        or binding.get("ram_mib") != RAM_MIB
        or not isinstance(values, list)
        or len(values) != 6
        or any(not isinstance(item, dict) for item in values)
        or {item.get("role") for item in values} != ROLES
        or len({item.get("id") for item in values}) != 6
        or len({item.get("sha256") for item in values}) != 6
        or binding.get("schema_sha256") != fingerprint(values)
        or any(binding.get(key) != value for key, value in GEOMETRY.items())
    ):
        raise ValueError("The complete recurrent model binding changed")
    for item in values:
        if component(session.get(ModelFile, item["id"]), item["role"]) != item:
            raise ValueError("The frozen recurrent model component changed")
        if item["role"] == "wan_high_noise" and item["id"] != primary.id:
            raise ValueError("The recurrent definition points to a different primary model")
    return deepcopy(binding)


def register_prepared(session, run, prepared, files):
    if (
        prepared.get("profile") != PROFILE
        or prepared.get("operation_id") != run.id
        or prepared.get("environment_prepared") is not True
        or prepared.get("manifest_sha256") != run.parameters.get("manifest_sha256")
        or prepared.get("manifest_sha256") != fingerprint(run.parameters.get("recipe"))
    ):
        raise ValueError("The recurrent activation differs from its reviewed setup")
    saved = run.task.metadata_json.get("runtime_preparation") or {}
    if saved.get("workload_accepted") is not True:
        raise ValueError("The recurrent CPU-offload workload needs explicit acceptance")
    runtime = checked_runtime(
        {
            "profile": PROFILE,
            "manifest_sha256": prepared["manifest_sha256"],
            "environment_id": fingerprint(
                {key: prepared[key] for key in ("profile", "manifest_sha256", "operation_id")}
            ),
        }
    )
    inputs = [item for item in run.parameters["recipe"]["inputs"] if item["kind"] == "model"]
    by_hash = {item["sha256"]: item for item in files}
    if len(inputs) != 6 or {item["role"] for item in inputs} != ROLES or len(by_hash) != 6:
        raise ValueError("The prepared recurrent bundle is incomplete")
    values = []
    for item in sorted(inputs, key=lambda item: item["role"]):
        found = by_hash.get(item["sha256"]) or {}
        row = session.get(ModelFile, found.get("model_file_id")) if found else None
        snapshot = component(row, item["role"])
        if snapshot["sha256"] != item["sha256"] or snapshot["size_bytes"] != item["size_bytes"]:
            raise ValueError("The prepared recurrent component differs from its reviewed recipe")
        values.append(snapshot)
    primary = session.get(ModelFile, next(item["id"] for item in values if item["role"] == "wan_high_noise"))
    binding = {
        "checkpoint_profile": CHECKPOINT_PROFILE,
        "schema_sha256": fingerprint(values),
        "managed_runtime": runtime,
        "components": values,
        "cpu_offload": True,
        "workload_accepted": True,
        "ram_mib": RAM_MIB,
        "minimum_physical_ram_mib": 24576,
        "minimum_vram_mib": 12288,
        "continuation_frames": 4,
        **GEOMETRY,
    }
    checked_binding(session, primary, binding)
    key = fingerprint({"kind": CHECKPOINT_PROFILE, "managed_runtime": runtime})
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.binding_key == key))
    video = {"sha256": primary.sha256, "binding": binding}
    if definition is not None and (
        definition.file_id != primary.id
        or definition.category != "video"
        or definition.metadata_json.get("video") != video
    ):
        raise ValueError("This recurrent engine already has a different model binding")
    if definition is None:
        definition = ModelDefinition(
            name=run.parameters["recipe"].get("name", "Wan 2.2 SVI Pro Q4 · Continuous video"),
            file_id=primary.id,
            binding_key=key,
            category="video",
            family="wan22-svi-pro",
            capabilities=["animate", "film"],
            status="registered",
            metadata_json={"video": video, "locally_qualified": False},
        )
        session.add(definition)
        session.flush()
    return {"definition_id": definition.id, "managed_runtime": runtime}
