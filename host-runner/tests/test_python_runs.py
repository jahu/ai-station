import base64
import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import python_job, python_runs
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.processes import ProcessManager
from ai_station_runner.python_container import read_output
from ai_station_runner.python_protocol import MAX_FILE
from fastapi.testclient import TestClient
from pydantic import ValidationError

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64


@pytest.fixture(autouse=True)
def isolated_python(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_PYTHON_IMAGE", "ai-station-python:test")
    clear_settings_cache()
    yield
    clear_settings_cache()


def request(**overrides):
    return python_runs.PythonRequest.model_validate(
        {
            "run_id": str(uuid4()),
            "project_id": str(uuid4()),
            "worktree_run_id": str(uuid4()),
            "script_relative": "src/process.py",
            "script_sha256": hashlib.sha256(b"print(1)").hexdigest(),
            "expected_outputs": ["report.csv"],
            "permissions": list(python_runs.PERMISSIONS),
            **overrides,
        }
    )


def reserve(body):
    root = python_runs.directory(str(body.run_id))
    root.mkdir(parents=True)
    (root / "inputs").mkdir()
    saved = {
        "request": body.model_dump(mode="json"),
        "digest": hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
        "image": IMAGE,
    }
    python_runs.save(root / "request.json", saved)
    return root, saved


def container(saved, **overrides):
    name, labels = python_runs.container_identity(saved)
    return {"Id": CID, "Image": IMAGE, "Name": "/" + name, "Config": {"Labels": labels}, **overrides}


@pytest.mark.parametrize(
    "values",
    [
        {"script_relative": "../secret.py"},
        {"script_relative": "/etc/a.py"},
        {"script_relative": "src/../a.py"},
        {"script_relative": "./script.py"},
        {"script_relative": "shell.sh"},
        {"expected_outputs": ["../secret"]},
        {"expected_outputs": ["same.txt", "same.txt"]},
        {"expected_outputs": []},
        {"maximum_runtime": True},
        {"maximum_runtime": 601},
        {"command": "bad"},
        {"image": "untrusted"},
        {"environment": {"TOKEN": "bad"}},
    ],
)
def test_python_request_rejects_host_paths_commands_and_unbounded_configuration(values):
    with pytest.raises(ValidationError):
        request(**values)


def test_native_python_api_requires_explicit_permission_and_rejects_extra_fields():
    from ai_station_runner.app import app

    api = TestClient(app)
    body = request().model_dump(mode="json")
    assert api.post("/v1/runs/python", json={**body, "permissions": ["filesystem_read"]}).status_code == 403
    assert api.post("/v1/runs/python", json={**body, "shell": "whoami"}).status_code == 422


def test_python_image_is_fixed_installed_and_protocol_checked(monkeypatch):
    image = {
        "Id": IMAGE,
        "Config": {
            "Entrypoint": python_runs.ENTRYPOINT,
            "User": "1000:1000",
            "Labels": {"ai-station.python.protocol": "1"},
        },
    }
    monkeypatch.setattr(python_runs, "docker", lambda *args, **kw: json.dumps(image))
    assert python_runs.capabilities()["available"]
    image["Config"]["Entrypoint"] = ["bash"]
    assert not python_runs.capabilities()["available"]


def test_source_snapshot_rejects_changed_symlink_and_hardlinked_files(tmp_path):
    source = tmp_path / "script.py"
    source.write_bytes(b"approved")
    digest = hashlib.sha256(b"approved").hexdigest()
    python_runs.copy_snapshot(source, tmp_path / "snapshot.py", digest, 100)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        python_runs.copy_snapshot(source, tmp_path / "bad.py", digest, 100)
    alias = tmp_path / "alias.py"
    alias.symlink_to(source)
    with pytest.raises(OSError):
        python_runs.copy_snapshot(alias, tmp_path / "bad.py", digest, 100)
    os.link(source, tmp_path / "hard.py")
    with pytest.raises(ValueError, match="regular"):
        python_runs.copy_snapshot(source, tmp_path / "bad.py", digest, 100)


def test_container_creation_is_hardened_and_journaled_before_docker_call(monkeypatch):
    body = request()
    root, saved = reserve(body)
    calls = []

    def docker(args):
        calls.append(args)
        assert json.loads((root / "container.json").read_text()) == {"state": "creating", "id": None}
        return CID

    monkeypatch.setattr(python_job, "docker", docker)
    monkeypatch.setattr(python_job, "inspect_container", lambda *args: container(saved))
    assert python_job.create_container(str(body.run_id), saved) == CID
    args = calls[0]
    for key, value in {
        "--network": "none",
        "--cap-drop": "ALL",
        "--memory": "512m",
        "--pids-limit": "64",
        "--pull": "never",
    }.items():
        assert args[args.index(key) + 1] == value
    assert "--read-only" in args and "--privileged" not in args
    mount = args[args.index("--mount") + 1]
    assert mount.endswith("dst=/inputs,readonly") and str(root / "inputs") in mount
    assert all("/var/run/docker.sock" not in arg for arg in args)
    with pytest.raises(ValueError, match="never replayed"):
        python_job.create_container(str(body.run_id), saved)


def test_stop_before_create_prevents_container_dispatch(monkeypatch):
    body = request()
    root, saved = reserve(body)
    python_runs.save(root / "cancel.json", {"requested": True})
    monkeypatch.setattr(python_job, "docker", lambda *args: pytest.fail("canceled create"))
    with pytest.raises(InterruptedError):
        python_job.create_container(str(body.run_id), saved)


def test_cleanup_checks_exact_owner_and_preserves_uncertain_create(monkeypatch):
    body = request()
    root, saved = reserve(body)
    python_runs.save(root / "container.json", {"state": "creating", "id": None})
    monkeypatch.setattr(python_runs, "inspect_container", lambda *args: None)
    assert python_runs.stop_container(str(body.run_id)) is False
    python_runs.save(root / "container.json", {"state": "created", "id": CID})
    calls = []
    monkeypatch.setattr(python_runs, "inspect_container", lambda *args: container(saved))
    monkeypatch.setattr(python_runs, "docker", lambda args: calls.append(args))
    assert python_runs.stop_container(str(body.run_id)) is True
    assert calls == [["rm", "--force", CID]]


def test_foreign_container_labels_or_id_cannot_be_stopped(monkeypatch):
    body = request()
    _, saved = reserve(body)
    monkeypatch.setattr(python_runs, "docker", lambda *args, **kw: json.dumps(container(saved)))
    with pytest.raises(ValueError, match="ownership"):
        python_runs.inspect_container(saved, "c" * 64)
    altered = container(saved)
    altered["Config"]["Labels"]["ai-station.python.owner"] = str(uuid4())
    monkeypatch.setattr(python_runs, "docker", lambda *args, **kw: json.dumps(altered))
    with pytest.raises(ValueError, match="ownership"):
        python_runs.inspect_container(saved)


def test_output_reader_rejects_aliases_fifos_oversize_and_hardlinks(tmp_path):
    good = tmp_path / "report.csv"
    good.write_bytes(b"price\n1\n")
    assert read_output("report.csv", str(tmp_path)) == good.read_bytes()
    (tmp_path / "link.csv").symlink_to(good)
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(tmp_path / "pipe")
    for name in ["link.csv", "alias/report.csv", "pipe"]:
        with pytest.raises((OSError, ValueError)):
            read_output(name, str(tmp_path))
    with (tmp_path / "big").open("wb") as handle:
        handle.truncate(MAX_FILE + 1)
    with pytest.raises(ValueError):
        read_output("big", str(tmp_path))
    os.link(good, tmp_path / "hard")
    with pytest.raises(ValueError):
        read_output("hard", str(tmp_path))


def test_native_export_only_adopts_expected_bounded_output_names():
    body = request()
    root, _ = reserve(body)
    result = []
    python_job.collect_output(
        str(body.run_id),
        body,
        {"event": "output", "name": "report.csv", "data": base64.b64encode(b"a,b\n1,2\n").decode()},
        result,
    )
    assert (root / "output-0.csv").read_bytes() == b"a,b\n1,2\n"
    assert result[0]["relative_path"] == f"runtime/python/{body.run_id}/output-0.csv"
    with pytest.raises(ValueError, match="duplicate"):
        python_job.collect_output(
            str(body.run_id), body, {"event": "output", "name": "report.csv", "data": ""}, result
        )


def test_process_manager_checks_python_cleanup_after_wrapper_disappears(tmp_path, monkeypatch):
    manager = ProcessManager(tmp_path)
    rid = str(uuid4())
    # Seed a finished owned record via an actual short process, not a fabricated pid.
    import sys
    import time

    manager.start(run_id=rid, argv=[sys.executable, "-c", "pass"], cwd=tmp_path, executor="python")
    monkeypatch.setattr(python_runs, "stop_container", lambda owner: owner != rid)
    deadline = time.monotonic() + 5
    while True:
        info = manager.inspect(rid)
        if not info["alive"] and not info.get("completion_pending"):
            break
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert info["cleanup_confirmed"] is False and info["status"] == "interrupted"


def test_dispatch_freezes_owned_script_and_never_replays_uncertain_start(tmp_path, monkeypatch):
    from ai_station_runner.processes import ProcessNotOwned

    body = request()
    workspace = tmp_path / "worktrees" / str(body.project_id) / str(body.worktree_run_id)
    (workspace / "src").mkdir(parents=True)
    source = workspace / body.script_relative
    source.write_bytes(b"print(1)")
    monkeypatch.setattr(python_runs, "capabilities", lambda: {"available": True, "image_id": IMAGE})
    monkeypatch.setattr(
        python_runs,
        "inspect_worktree",
        lambda *args: {
            "state": "ready",
            "project_id": str(body.project_id),
            "relative_path": str(workspace.relative_to(tmp_path)),
        },
    )

    class Manager:
        def inspect(self, run_id):
            raise ProcessNotOwned(run_id)

        def start(self, **kwargs):
            raise RuntimeError("lost process-start response")

    with pytest.raises(RuntimeError, match="lost"):
        python_runs.start_python(Manager(), body)
    stage = python_runs.directory(str(body.run_id)) / "inputs/script.py"
    source.write_bytes(b"changed after snapshot")
    assert stage.read_bytes() == b"print(1)"
    with pytest.raises(ValueError, match="inspection"):
        python_runs.start_python(Manager(), body)
    assert stage.read_bytes() == b"print(1)"


def test_mount_csv_quoting_keeps_comma_in_owned_data_path(tmp_path, monkeypatch):
    import csv

    body = request()
    _, saved = reserve(body)
    root = tmp_path / "owned,comma"
    root.mkdir()
    monkeypatch.setattr(python_job, "directory", lambda run_id: root)
    calls = []
    monkeypatch.setattr(python_job, "docker", lambda args: calls.append(args) or CID)
    monkeypatch.setattr(python_job, "inspect_container", lambda *args: container(saved))
    python_job.create_container(str(body.run_id), saved)
    args = calls[0]
    assert next(csv.reader([args[args.index("--mount") + 1]])) == [
        "type=bind",
        "src=" + str(root / "inputs"),
        "dst=/inputs",
        "readonly",
    ]


def test_script_snapshot_excludes_concurrent_worktree_mutation(tmp_path):

    wid = str(uuid4())
    with python_runs.snapshot_lock(wid):
        with pytest.raises(BlockingIOError):
            with python_runs.snapshot_lock(wid):
                pytest.fail("parallel snapshot obtained an exclusive worktree lock")
    with python_runs.snapshot_lock(wid):
        pass
