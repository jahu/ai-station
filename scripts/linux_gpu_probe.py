"""Native installer-only CUDA observation; never a workload/API command surface."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from desktop_versions import directory, read_private

UUID = r"GPU-[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
QUERY = """import ctypes,json
driver=ctypes.CDLL('libcuda.so.1')
def checked(code):
 if code: raise RuntimeError('CUDA observation failed')
class DeviceUUID(ctypes.Structure):
 _fields_=[('bytes',ctypes.c_ubyte*16)]
checked(driver.cuInit(0));count=ctypes.c_int();checked(driver.cuDeviceGetCount(ctypes.byref(count)))
if not 0<count.value<=16: raise RuntimeError('CUDA device count is unavailable')
read_uuid=getattr(driver,'cuDeviceGetUuid_v2',driver.cuDeviceGetUuid)
devices=[]
for index in range(count.value):
 device=ctypes.c_int();checked(driver.cuDeviceGet(ctypes.byref(device),index))
 value=DeviceUUID();checked(read_uuid(ctypes.byref(value),device))
 raw=bytes(value.bytes).hex();devices.append('GPU-'+raw[:8]+'-'+raw[8:12]+'-'+raw[12:16]+'-'+raw[16:20]+'-'+raw[20:])
print(json.dumps({'uuids':devices}))
"""


def native_linux():
    import platform

    return (
        platform.system() == "Linux"
        and "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower()
    )


def gpu_uuids():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        values = result.stdout.split() if result.returncode == 0 else []
        if (
            0 < len(values) <= 16
            and len(set(values)) == len(values)
            and all(re.fullmatch(UUID, v) for v in values)
        ):
            return values
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def nvidia_present():
    try:
        for node in Path("/sys/bus/pci/devices").iterdir():
            try:
                if (node / "vendor").read_text().strip() == "0x10de" and int(
                    (node / "class").read_text(), 16
                ) >> 16 == 3:
                    return True
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return False


def write_private(path, value):
    directory(path.parent)
    if path.exists() or path.is_symlink():
        read_private(path, 16384)
    descriptor, temporary = tempfile.mkstemp(prefix=".gpu-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def command(engine, *args, timeout=20):
    result = subprocess.run(
        engine.command(*args),
        env=engine.environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if len(result.stdout) > 1024**2:
        raise ValueError("Graphics observation exceeds its expected bound")
    return result


def read_record(path):
    value = json.loads(read_private(path, 16384))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "name", "token", "image", "user", "query_sha256", "container_id"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or (value["container_id"] is not None and not re.fullmatch(r"[a-f0-9]{64}", value["container_id"]))
        or not re.fullmatch(r"ai-station-gpu-check-[a-f0-9]{32}", value.get("name", ""))
        or not re.fullmatch(r"[a-f0-9]{32}", value.get("token", ""))
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", value.get("image", ""))
        or value.get("user") != f"{os.getuid()}:{os.getgid()}"
        or not re.fullmatch(r"[a-f0-9]{64}", value.get("query_sha256", ""))
    ):
        raise ValueError("Inspect the previous graphics observation receipt")
    return value


def observed_container(engine, record):
    result = command(engine, "inspect", "--type", "container", record["name"])
    if result.returncode:
        if "No such" in result.stderr or "not found" in result.stderr:
            return None
        raise ValueError("The graphics observation container could not be inspected")
    values = json.loads(result.stdout)
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError("Unexpected graphics observation inventory")
    item = values[0]
    config = item.get("Config", {})
    host = item.get("HostConfig", {})
    cmd = config.get("Cmd", [])
    if (
        not re.fullmatch(r"[a-f0-9]{64}", item.get("Id", ""))
        or (record["container_id"] is not None and item.get("Id") != record["container_id"])
        or item.get("Name") != "/" + record["name"]
        or item.get("Image") != record["image"]
        or config.get("Labels", {}).get("ai-station.native-gpu-probe") != record["token"]
        or config.get("User") != record["user"]
        or config.get("Entrypoint") != ["/opt/venv/bin/python"]
        or len(cmd) != 4
        or cmd[:3] != ["-I", "-B", "-c"]
        or hashlib.sha256(cmd[3].encode()).hexdigest() != record["query_sha256"]
        or item.get("Mounts")
        or host.get("NetworkMode") != "none"
        or host.get("Privileged") is not False
        or host.get("ReadonlyRootfs") is not True
    ):
        raise ValueError("Graphics probe ownership changed; no container was signaled")
    return item


def cleanup(engine, path):
    if not path.exists() and not path.is_symlink():
        return
    record = read_record(path)
    item = observed_container(engine, record)
    if item is not None:
        if item["State"].get("Running"):
            result = command(engine, "stop", "--time", "2", item["Id"], timeout=10)
            if result.returncode:
                raise ValueError("The owned graphics probe is still stopping")
        if command(engine, "rm", item["Id"]).returncode:
            raise ValueError("The owned graphics probe still needs cleanup")
    path.unlink()


def probe(root, image, engine, uuids):
    if (
        not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
        or not uuids
        or len(uuids) > 16
        or len(uuids) != len(set(uuids))
        or any(not re.fullmatch(UUID, v) for v in uuids)
    ):
        raise ValueError("Use the verified application image and observed GPU identities")
    path = root / "gpu-probe.json"
    cleanup(engine, path)
    record = {
        "schema": 1,
        "name": "ai-station-gpu-check-" + uuid4().hex,
        "token": uuid4().hex,
        "image": image,
        "user": f"{os.getuid()}:{os.getgid()}",
        "query_sha256": hashlib.sha256(QUERY.encode()).hexdigest(),
        "container_id": None,
    }
    write_private(path, record)
    try:
        result = command(
            engine,
            "create",
            "--pull",
            "never",
            "--name",
            record["name"],
            "--label",
            "ai-station.native-gpu-probe=" + record["token"],
            "--network",
            "none",
            "--user",
            record["user"],
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--gpus",
            '"device=' + ",".join(uuids) + '"',
            "--env",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "--env",
            "CUDA_VISIBLE_DEVICES=" + ",".join(uuids),
            "--entrypoint",
            "/opt/venv/bin/python",
            image,
            "-I",
            "-B",
            "-c",
            QUERY,
        )
        if result.returncode:
            return False
        identity = result.stdout.strip()
        item = observed_container(engine, record)
        if item is None or item["Id"] != identity:
            raise ValueError("Graphics probe creation is uncertain")
        record["container_id"] = identity
        write_private(path, record)
        result = command(engine, "start", "--attach", identity, timeout=30)
        if result.returncode:
            return False
        observed = json.loads(result.stdout)
        return isinstance(observed, dict) and observed.get("uuids") == uuids
    finally:
        cleanup(engine, path)
