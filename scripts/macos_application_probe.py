"""Explicit native installed-package qualification; no source-path injection or model."""

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

SITE = "lib/python3.12/site-packages/ai_station_runner"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Native package link escapes its interpreter")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
        elif not path.is_dir():
            raise ValueError("Native package contains a special file")
    return result


def receipt(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024**2:
        raise ValueError("Use a bounded regular native package receipt")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Native package receipt is not an object")
    return value


def verify_layer(layer, architecture, root):
    if layer.resolve(strict=True) != layer or root.resolve(strict=True) != root:
        raise ValueError("Native qualification requires canonical package/source roots")
    value = receipt(layer / "application-python.json")
    base = receipt(layer / "native-python.json")
    frozen = json.loads((root / "packaging/macos" / (architecture + ".json")).read_text())
    manifest_hash = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if (
        value.get("schema") != 1
        or value.get("profile") != f"application-python312-darwin-{architecture}-v1"
        or value.get("architecture") != architecture
        or value.get("source_head") != head
        or not re.fullmatch(r"[a-f0-9]{40}", head)
        or value.get("source_dirty") is not False
        or value.get("native_application_executed") is not False
        or value.get("macos_installer_qualified") is not False
        or value.get("base_inventory_unchanged") is not True
        or value.get("base_manifest_sha256") != manifest_hash
        or base.get("manifest_sha256") != manifest_hash
        or base.get("architecture") != architecture
        or base.get("python_version") != "3.12.14"
        or value.get("base_receipt_sha256") != digest(layer / "native-python.json")
    ):
        raise ValueError("Application Python identity differs from reviewed source/recipe")
    actual = inventory(layer)
    recorded = dict(actual)
    recorded.pop("application-python.json")
    if (
        recorded != value.get("files")
        or not isinstance(base.get("files"), dict)
        or any(actual.get(name) != file_hash for name, file_hash in base["files"].items())
    ):
        raise ValueError("Application/base interpreter inventory changed")
    names = (
        subprocess.check_output(["git", "ls-files", "-z", "--", "host-runner/ai_station_runner"], cwd=root)
        .decode()
        .split("\0")
    )
    sources = {}
    package = root / "host-runner/ai_station_runner"
    for name in filter(None, names):
        source = root / name
        if source.resolve(strict=True) != source or not source.is_file():
            raise ValueError("Reviewed Runner source changed its canonical file boundary")
        sources[source.relative_to(package).as_posix()] = digest(source)
    installed = {
        name.removeprefix(SITE + "/"): file_hash
        for name, file_hash in actual.items()
        if name.startswith(SITE + "/")
    }
    if not sources or sources != value.get("runner_source_files") or installed != sources:
        raise ValueError("Installed Runner differs from tracked package bytes")
    return value, actual


def stop_child(child):
    if child is None:
        return
    if child.poll() is None:
        child.terminate()  # Immediate unreaped Popen handle, never a caller PID.
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def fixture_owner(root, identity):
    """Fixed sleeping fixture only; normal exit hands its real journal to main."""
    if (
        platform.system() != "Darwin"
        or platform.machine() not in {"arm64", "x86_64"}
        or sys.version_info[:3] != (3, 12, 14)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
    ):
        raise RuntimeError("The fixture owner requires the isolated native application Python")
    if (
        root.resolve(strict=True) != root
        or root.parent != Path("/private/tmp")
        or not re.fullmatch(r"ais-app-[a-z0-9_]{8}", root.name)
        or not root.is_dir()
        or root.stat().st_uid != os.geteuid()
        or stat.S_IMODE(root.stat().st_mode) != 0o700
        or any(root.iterdir())
        or str(UUID(identity)) != identity
    ):
        raise ValueError("The fixture owner requires its fresh private probe directory and UUID")
    from ai_station_runner.runner_platform import create_process_manager

    manager = create_process_manager(root / "data", grace_seconds=0.05)
    try:
        started = manager.start(
            run_id=identity,
            argv=[sys.executable, "-IB", "-c", "import time;time.sleep(60)"],
            cwd=root,
            executor="packaged-runner-qualification",
            env={"PATH": os.defpath, "HOME": str(root)},
        )
        descriptor = os.open(root / "owner.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump({"run_id": identity, "pid": started["pid"], "owner_pid": os.getpid()}, output)
            output.flush()
            os.fsync(output.fileno())
        # No shutdown on successful handoff. This helper exits; its daemon
        # reaper is gone before the normal Runner is allowed to adopt the child.
    except BaseException:
        manager.shutdown()
        raise


def owner_handoff(root, helper, identity):
    value = receipt(root / "owner.json")
    if (
        helper.returncode != 0
        or value.get("owner_pid") != helper.pid
        or value.get("run_id") != identity
        or type(value.get("pid")) is not int
        or not 0 < value["pid"] < 2**31
    ):
        raise ValueError("Original fixture owner exit/handoff was not confirmed")
    return value


def exercise_runner():
    import httpx
    from ai_station_runner.runner_platform import create_process_manager
    from ai_station_runner.source_identity import SOURCE_FINGERPRINT

    root = Path(tempfile.mkdtemp(prefix="ais-app-", dir="/private/tmp")).resolve()
    data, socket = root / "data", root / "uds/runner.sock"
    owner, server, unrelated, helper = None, None, None, None
    identity = str(uuid4())
    result, cleanup = {}, []
    try:
        helper = subprocess.Popen(
            [sys.executable, "-IB", str(Path(__file__).resolve()), "--fixture-owner", str(root), identity],
            cwd=root,
            env={"PATH": os.defpath, "HOME": str(root)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        helper.wait(timeout=20)
        if helper.returncode != 0:
            (root / "owner.stderr").write_bytes(helper.stderr.read(4096))
            raise RuntimeError("Original native fixture owner did not complete")
        started = owner_handoff(root, helper, identity)
        unrelated = subprocess.Popen(
            [sys.executable, "-IB", "-c", "import time;time.sleep(60)"],
            env={"PATH": os.defpath, "HOME": str(root)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "AI_STATION_DATA_HOST_PATH": str(data),
            "AI_STATION_RUNNER_SOCKET": str(socket),
            "AI_STATION_CANCEL_GRACE_SECONDS": "0.05",
        }
        command = [sys.executable, "-IB", "-m", "ai_station_runner.main"]
        with (root / "runner.stderr").open("wb") as error:
            server = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=error,
            )
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket)),
            base_url="http://runner",
            timeout=5,
            trust_env=False,
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Installed native Runner exited before readiness")
                try:
                    health = client.get("/health")
                    if health.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("Installed native Runner readiness exceeded its budget")
                time.sleep(0.05)
            if (
                health.json().get("data_dir") != str(data)
                or health.json().get("source_fingerprint") != SOURCE_FINGERPRINT
            ):
                raise ValueError("Installed Runner health/source identity changed")
            if (
                stat.S_IMODE(socket.stat().st_mode) != 0o600
                or stat.S_IMODE(socket.parent.stat().st_mode) != 0o700
            ):
                raise ValueError("Installed Runner socket is not private")
            duplicate = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=20)
            if duplicate.returncode == 0 or b"already owns" not in duplicate.stderr:
                raise ValueError("Installed Runner did not reject its second owner")
            observed = client.get("/v1/process/" + identity)
            if (
                observed.status_code != 200
                or observed.json().get("pid") != started["pid"]
                or not observed.json().get("alive")
            ):
                raise ValueError("Installed Runner did not recover its exact owned process")
            if client.post("/v1/process/cancel", json={"run_id": str(uuid4())}).status_code != 404:
                raise ValueError("Installed Runner accepted an unknown process owner")
            stopped = client.post("/v1/process/cancel", json={"run_id": identity})
            if (
                stopped.status_code != 200
                or stopped.json().get("status") != "canceled"
                or stopped.json().get("alive")
            ):
                raise ValueError("Installed Runner did not confirm owned Stop")
            if (
                unrelated.poll() is not None
                or client.post("/v1/llama/load", json={}).status_code != 422
                or client.post("/v1/runs/photo", json={}).status_code != 503
            ):
                raise ValueError("Installed Runner changed unowned work or admitted an unqualified adapter")
        server.terminate()
        if server.wait(timeout=15) != 0 or socket.exists():
            raise ValueError("Installed Runner did not complete normal socket shutdown")
        result = {
            "owner_process_exit_confirmed": True,
            "normal_Runner_main_passed": True,
            "private_socket_passed": True,
            "duplicate_owner_refused": True,
            "owned_process_recovered": True,
            "unknown_owner_refused": True,
            "owned_stop_confirmed": True,
            "unrelated_process_survived": True,
            "socket_cleanup_confirmed": True,
        }
    finally:
        try:
            stop_child(server)
        except Exception:
            cleanup.append("runner")
        try:
            stop_child(helper)
            if helper is not None and helper.stderr is not None:
                helper.stderr.close()
        except Exception:
            cleanup.append("original_owner")
        if (data / "runtime/processes.json").exists():
            try:
                owner = create_process_manager(data, grace_seconds=0.05)
                owner.shutdown()
                if owner.inspect(identity).get("alive"):
                    raise ValueError("Original managed group is still alive")
            except Exception:
                cleanup.append("managed_process")
        try:
            stop_child(unrelated)
        except Exception:
            cleanup.append("unrelated_fixture")
        if cleanup:
            # Retain ownership proof on uncertainty; never erase a live journal.
            raise RuntimeError("Native fixture cleanup requires inspection")
        if result:
            shutil.rmtree(root)
    return result


def main():
    if (
        len(sys.argv) != 2
        or sys.argv[1] not in {"arm64", "x86_64"}
        or platform.system() != "Darwin"
        or platform.machine() != sys.argv[1]
        or sys.version_info[:3] != (3, 12, 14)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
    ):
        raise RuntimeError("Use the exact isolated/no-bytecode native application Python and architecture")
    layer = Path(sys.executable).resolve().parent.parent
    root = Path(__file__).resolve().parent.parent
    if Path(sys.prefix).resolve() != layer:
        raise ValueError("Installed application Python prefix changed")
    value, before = verify_layer(layer, sys.argv[1], root)
    module = importlib.util.find_spec("ai_station_runner")
    if (
        module is None
        or not isinstance(module.origin, str)
        or Path(module.origin).resolve() != layer / SITE / "__init__.py"
    ):
        raise ValueError("Runner import did not resolve the installed wheel")
    result = exercise_runner()
    if inventory(layer) != before:
        raise ValueError("Installed Runner execution changed the complete application interpreter inventory")
    result.update(
        platform="Darwin",
        architecture=platform.machine(),
        os_version=platform.mac_ver()[0],
        python_version=platform.python_version(),
        source_head=value["source_head"],
        application_receipt_sha256=digest(layer / "application-python.json"),
        installed_Runner_import_passed=True,
        layer_inventory_unchanged=True,
        model_inference_tested=False,
        DockerDesktop_transport_tested=False,
        Metal_inference_tested=False,
        macos_installer_qualified=False,
    )
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--fixture-owner":
        fixture_owner(Path(sys.argv[2]), sys.argv[3])
    else:
        main()
