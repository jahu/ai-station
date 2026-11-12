"""Durable ownership of fixed preparation containers; never arbitrary Docker input.

The caller supplies the already private native setup directory and frozen daemon.
Fresh setup remains unavailable until the complete job/Stop/recovery is integrated.
"""

from copy import deepcopy
from urllib.parse import quote
from uuid import UUID

from ai_station_runner.motion_prepare_plan import BASES, fingerprint, inspect_owned, stage_spec
from ai_station_runner.runtime_install import atomic_json, load_json
from ai_station_runner.runtime_setup import validate_image


class OwnershipUncertain(ValueError):
    pass


def filename(stage):
    if stage not in BASES:
        raise ValueError("Use a fixed renderer preparation stage")
    return "motion-stage-" + stage + ".json"


def checked_daemon(api, daemon_id):
    result = api.get("/info")
    result.raise_for_status()
    if result.json().get("ID") != daemon_id:
        raise OwnershipUncertain("Renderer preparation Docker daemon changed")


def record(folder, stage, identity, request_hash, daemon_id):
    saved = load_json(folder / filename(stage))
    if saved is None:
        return None
    expected = {
        "protocol": 1,
        "run_id": str(UUID(str(identity))),
        "request_hash": request_hash,
        "daemon_id": daemon_id,
        "spec_sha256": fingerprint(stage_spec(stage, identity, request_hash)),
        "stage": stage,
        "container_name": "ai-station-motion-prepare-" + str(UUID(str(identity))) + "-" + stage,
    }
    if any(saved.get(key) != value for key, value in expected.items()):
        raise OwnershipUncertain("Renderer preparation stage receipt changed")
    return saved


def observe(api, saved):
    checked_daemon(api, saved["daemon_id"])
    response = api.get("/images/" + quote(BASES[saved["stage"]], safe="") + "/json")
    response.raise_for_status()
    base = response.json()
    validate_image(base, BASES[saved["stage"]])
    if {key: base[key] for key in saved["base"]} != saved["base"]:
        raise OwnershipUncertain("Renderer preparation base image changed")
    coordinate = saved.get("container_id") or saved["container_name"]
    response = api.get("/containers/" + quote(coordinate, safe="") + "/json")
    if response.status_code == 404:
        if saved.get("container_id"):
            return None
        raise OwnershipUncertain("A renderer stage creation is unacknowledged; inspect the original intent")
    response.raise_for_status()
    value = response.json()
    inspect_owned(
        value,
        saved["base"],
        saved["stage"],
        saved["run_id"],
        saved["request_hash"],
        container_id=saved.get("container_id") or value.get("Id", ""),
    )
    if value.get("Name") != "/" + saved["container_name"]:
        raise OwnershipUncertain("Renderer preparation container name changed")
    policy = deepcopy({key: value.get(key) for key in ("Config", "HostConfig", "Mounts", "Image")})
    # Docker changes this optional false pointer to null after starting a
    # cgroup-v2 container. Both leave OOM killing enabled; true is refused by
    # inspect_owned. Compare the COMPLETE prior hash under just these two
    # representations, then retain one canonical hash. No other field is relaxed.
    policy["HostConfig"]["OomKillDisable"] = None
    equivalent = {fingerprint(policy)}
    policy["HostConfig"]["OomKillDisable"] = False
    canonical = fingerprint(policy)
    equivalent.add(canonical)
    if saved.get("inspected_policy") and saved["inspected_policy"] not in equivalent:
        raise OwnershipUncertain("Renderer preparation inspected policy changed")
    return value, canonical


def create(api, folder, stage, identity, request_hash, daemon_id):
    """Create once; a lost reply can adopt only the original exact owned stage.

    The native caller serializes setup mutations and checks Stop/deadline before
    calling. This helper never reissues an uncertain create operation.
    """
    spec = stage_spec(stage, identity, request_hash)
    saved = record(folder, stage, identity, request_hash, daemon_id)
    if saved is None:
        checked_daemon(api, daemon_id)
        response = api.get("/images/" + quote(BASES[stage], safe="") + "/json")
        response.raise_for_status()
        base = response.json()
        validate_image(base, BASES[stage])
        saved = {
            "protocol": 1,
            "run_id": str(UUID(str(identity))),
            "request_hash": request_hash,
            "daemon_id": daemon_id,
            "spec_sha256": fingerprint(spec),
            "stage": stage,
            "container_name": "ai-station-motion-prepare-" + str(UUID(str(identity))) + "-" + stage,
            "base": {key: base[key] for key in ("Id", "RepoDigests", "Os", "Architecture", "Config")},
            "create_started": True,
        }
        atomic_json(folder, filename(stage), saved)
        # If the daemon accepted this request but its reply is lost, the saved
        # name and closed specification are the only adoption authority.
        response = api.post("/containers/create", params={"name": saved["container_name"]}, json=spec)
        response.raise_for_status()
        saved["container_id"] = response.json()["Id"]
        atomic_json(folder, filename(stage), saved)
    result = observe(api, saved)
    if result is None:
        raise OwnershipUncertain("The original renderer preparation container is gone; do not recreate it")
    value, policy = result
    saved.update(container_id=value["Id"], inspected_policy=policy)
    atomic_json(folder, filename(stage), saved)
    return saved


def stop_and_remove(api, folder, stage, identity, request_hash, daemon_id):
    saved = record(folder, stage, identity, request_hash, daemon_id)
    if saved is None:
        return True
    result = observe(api, saved)
    if result is None:
        return True
    value, policy = result
    coordinate = value["Id"]
    saved.update(container_id=coordinate, inspected_policy=policy)
    atomic_json(folder, filename(stage), saved)
    if value.get("State", {}).get("Running"):
        response = api.post("/containers/" + coordinate + "/stop", params={"t": 10})
        response.raise_for_status()
        result = observe(api, saved)
        if result is None:
            return True
        if result[0].get("State", {}).get("Running"):
            raise OwnershipUncertain("The owned renderer preparation stage is still running")
    response = api.delete("/containers/" + coordinate, params={"force": "false", "v": "false"})
    response.raise_for_status()
    if observe(api, saved) is not None:
        raise OwnershipUncertain("Renderer preparation cleanup is not confirmed")
    return True
