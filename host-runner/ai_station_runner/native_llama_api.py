"""Native text models behind the existing typed llama.cpp API.

SDK references are opaque outside Runner. The single app ProcessManager owns
every native child; native inference sockets are never in its container mount.
"""

import hashlib
import os
import stat
import sys
import threading
from pathlib import Path

from fastapi import HTTPException

from ai_station_runner.config import get_settings
from ai_station_runner.darwin_llama import NativeLlamaManager, NativeLoad
from ai_station_runner.darwin_llama_environment import Environment
from ai_station_runner.environment_files import read_json
from ai_station_runner.native_llama_request import NativeModelLoad
from ai_station_runner.runtime_install import atomic_json

_manager = None
_lock = threading.Lock()
SOCKET_PARENT = Path("/private/tmp")


def socket_storage(root):
    """Short, private and installation-bound; never adopt unrecognized storage."""
    root_hash = hashlib.sha256(os.fsencode(root)).hexdigest()
    parent = SOCKET_PARENT.resolve(strict=True)
    folder = parent / f"ais-m-{os.geteuid()}-{root_hash[:20]}"
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Native model socket storage must remain private and owned")
    marker = folder / "owner.json"
    expected = {"schema": 1, "uid": os.geteuid(), "data_root_sha256": root_hash}
    if not marker.exists() and not marker.is_symlink():
        if any(folder.iterdir()):
            raise ValueError("Inspect unrecognized native model socket storage")
        atomic_json(folder, marker.name, expected)
    if read_json(marker) != expected:
        raise ValueError("Native model socket storage belongs to another installation")
    return folder


def manager():
    global _manager
    if sys.platform != "darwin":
        raise HTTPException(503, "Native Mac models require a matching Host Runner")
    from ai_station_runner.app import manager as processes

    owner = processes()
    root = get_settings().host_data_dir().resolve(strict=True)
    with _lock:
        if _manager is not None and (_manager.processes is not owner or _manager.root != root):
            _manager.close()
            _manager = None
        if _manager is None:
            _manager = NativeLlamaManager(root, socket_storage(root), processes=owner)
        return _manager


def close():
    global _manager
    with _lock:
        if _manager is not None:
            _manager.close()
            _manager = None


def call(operation, *args):
    try:
        return getattr(manager(), operation)(*args)
    except KeyError as exc:
        raise HTTPException(404, "Owned native model not found") from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(409, "Native model requires inspection before continuing") from exc


def load(body: NativeModelLoad):
    if set(body.permissions) != {"manage_models", "filesystem_read"}:
        raise HTTPException(403, "Native models require model management and filesystem read")
    if sys.platform != "darwin":
        raise HTTPException(503, "Native Mac models require a matching Host Runner")

    try:
        environment = Environment(body.runtime_profile)
        root = get_settings().host_data_dir().resolve(strict=True)
        observed = environment.resolve_id(root, body.environment_id)["observation"]
        request = body.model_dump(
            exclude={"runtime_profile", "environment_id", "app_owned", "gpus", "cache_type"}
        )
        request.update(
            architecture=environment.architecture,
            compute="cpu",
            bundle_operation_id=observed["operation_id"],
            bundle_manifest_sha256=observed["manifest_sha256"],
        )
        return call("load", NativeLoad.model_validate(request))
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "The prepared native SDK requires inspection") from exc


async def completion(identity, body, incoming):
    try:
        return await manager().completion(identity, body, incoming)
    except KeyError as exc:
        raise HTTPException(404, "Owned native model not found") from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(409, "Native model requires inspection before continuing") from exc
