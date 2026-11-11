import copy
import json
import os
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import motion_owner as owner
from ai_station_runner import motion_runtime as runtime
from ai_station_runner.motion_assets import request_digest
from ai_station_runner.motion_contract import MotionRequest
from ai_station_runner.processes import ProcessManager, ProcessNotOwned


def request():
    return MotionRequest.model_validate(
        dict(
            run_id=str(uuid4()),
            deadline_at=time.time() + 300.0,
            observation="a" * 64,
            permissions=["filesystem_read", "workspace_write"],
            composition=dict(
                style=dict(palette=["#336699"]), scenes=[dict(title="A visual idea", duration_frames=60)]
            ),
        )
    )


def saved(root, body):
    folder = owner.directory(root, str(body.run_id))
    folder.mkdir(parents=True)
    value = dict(
        request=body.model_dump(mode="json"),
        digest=request_digest(body),
        image="sha256:" + "b" * 64,
        recipe="c" * 64,
        user=f"{os.getuid()}:{os.getgid()}",
        connection={"host": "unix:///test/docker.sock", "daemon_id": "daemon"},
    )
    owner.save(folder / "request.json", value)
    return folder, value


def container(root, value):
    name, labels = owner.identity(value)
    return dict(
        Id="d" * 64,
        Image=value["image"],
        Name="/" + name,
        Config=dict(
            User=value["user"],
            Entrypoint=["python", "-m", "ai_station_runner.motion_container"],
            Cmd=[],
            Labels=labels,
        ),
        HostConfig=dict(
            NetworkMode="none",
            Runtime="runc",
            Privileged=False,
            ReadonlyRootfs=True,
            Devices=[],
            DeviceRequests=[],
            PortBindings={},
            CapAdd=[],
            CapDrop=["ALL"],
            SecurityOpt=["no-new-privileges"],
            Memory=4096 * 1024**2,
            MemorySwap=4096 * 1024**2,
            NanoCpus=4_000_000_000,
            PidsLimit=512,
            CgroupnsMode="private",
            Tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=512m"},
            PidMode="",
            IpcMode="private",
        ),
        Mounts=[
            dict(
                Type="bind",
                Source=str(owner.directory(root, value["request"]["run_id"]) / "work"),
                Destination="/work",
                RW=True,
            )
        ],
        State=dict(Running=False, ExitCode=0),
    )


def test_fixed_create_cleanup_only_signals_verified_id(tmp_path, monkeypatch):
    body = request()
    folder, value = saved(tmp_path, body)
    item = container(tmp_path, value)
    calls = []

    def docker(args, **kw):
        assert kw["bound"] == value["connection"]
        calls.append(args)
        if args[0] == "create":
            return item["Id"]
        if args[0] == "inspect":
            return json.dumps(item)
        if args[0] == "rm":
            assert args == ["rm", "--force", item["Id"]]
            return item["Id"]
        raise AssertionError(args)

    monkeypatch.setattr(owner, "docker", docker)
    assert owner.create(tmp_path, value) == item["Id"]
    create = calls[0]
    assert create[-1] == value["image"] and create[create.index("--network") + 1] == "none"
    assert "--gpus" not in create and "-p" not in create
    assert owner.stop(tmp_path, str(body.run_id), cancel=True)
    assert (folder / "cancel.json").is_file()
    with pytest.raises(InterruptedError):
        owner.create(tmp_path, value)
    assert sum(args[0] == "create" for args in calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        ("Image", "sha256:" + "e" * 64),
        ("Id", "f" * 64),
        ("Config.Labels.ai-station.motion.request", "e" * 64),
        ("Config.User", "0:0"),
        ("Config.Entrypoint", ["sh"]),
        ("HostConfig.NetworkMode", "host"),
        ("HostConfig.Privileged", True),
        ("HostConfig.ReadonlyRootfs", False),
        ("HostConfig.MemorySwap", -1),
        ("HostConfig.Runtime", "nvidia"),
        ("HostConfig.PortBindings", {"80/tcp": [{"HostPort": "80"}]}),
        ("HostConfig.DeviceRequests", [{"Count": -1}]),
        ("HostConfig.Tmpfs", {}),
        ("Mounts", []),
    ],
)
def test_changed_container_never_authorizes_signal(tmp_path, monkeypatch, change):
    body = request()
    folder, value = saved(tmp_path, body)
    item = container(tmp_path, value)
    owner.save(folder / "container.json", dict(state="created", id=item["Id"]))
    keys = change[0].split(".")
    if keys[:2] == ["Config", "Labels"]:
        item["Config"]["Labels"][".".join(keys[2:])] = change[1]
    else:
        node = item
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = change[1]

    def docker(args, **kw):
        assert args[0] == "inspect", "Changed ownership must never reach removal"
        return json.dumps(item)

    monkeypatch.setattr(owner, "docker", docker)
    with pytest.raises(ValueError):
        owner.stop(tmp_path, str(body.run_id))


def test_lost_creation_ack_never_replays_or_claims_cleanup(tmp_path, monkeypatch):
    body = request()
    folder, value = saved(tmp_path, body)
    owner.save(folder / "container.json", dict(state="creating", id=None))
    monkeypatch.setattr(owner, "docker", lambda args, **kw: None)
    assert owner.stop(tmp_path, str(body.run_id)) is False
    with pytest.raises(ValueError, match="never replayed"):
        owner.create(tmp_path, value)


def test_lost_ack_can_recover_exact_owned_container_and_remove(tmp_path, monkeypatch):
    body = request()
    folder, value = saved(tmp_path, body)
    item = container(tmp_path, value)
    calls = []
    owner.save(folder / "container.json", dict(state="creating", id=None))

    def docker(args, **kw):
        calls.append(args)
        return json.dumps(item) if args[0] == "inspect" else item["Id"]

    monkeypatch.setattr(owner, "docker", docker)
    assert owner.stop(tmp_path, str(body.run_id))
    assert calls[-1] == ["rm", "--force", item["Id"]]
    assert owner.stop(tmp_path, str(body.run_id))
    assert len(calls) == 2


@pytest.mark.parametrize("key,value", [("image", []), ("recipe", None), ("connection", []), ("request", {})])
def test_corrupt_ownership_fails_closed(tmp_path, key, value):
    body = request()
    folder, record = saved(tmp_path, body)
    record[key] = value
    owner.save(folder / "request.json", record)
    with pytest.raises(ValueError):
        owner.load(tmp_path, str(body.run_id))


class Manager:
    def __init__(self, root):
        self.data_dir = root
        self.started = None

    def inspect(self, rid):
        if self.started:
            return {"executor": "motion_render", "pid": 123}
        raise ProcessNotOwned(rid)

    def start(self, **kw):
        self.started = kw
        return self.inspect(kw["run_id"])


def test_launch_and_duplicate_use_one_frozen_receipt(tmp_path, monkeypatch):
    body = request()
    manager = Manager(tmp_path)
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(runtime, "available", lambda: True)
    monkeypatch.setattr(
        runtime,
        "image",
        lambda s: dict(
            image_id="sha256:" + "b" * 64,
            recipe_sha256="c" * 64,
            connection={"host": "unix:///test/docker.sock", "daemon_id": "daemon"},
        ),
    )
    monkeypatch.setattr(runtime, "observation", lambda s: "a" * 64)
    monkeypatch.setattr(runtime, "scope_prefix", lambda rid, ram: ["fixed-scope", str(ram)])
    runtime.start(manager, body)
    assert manager.started["argv"][:2] == ["fixed-scope", "256"]
    assert manager.started["env"]["AI_STATION_DATA_HOST_PATH"] == str(tmp_path)
    assert manager.started["env"]["CUDA_VISIBLE_DEVICES"] == ""
    original = copy.deepcopy(manager.started)
    runtime.start(manager, body)
    assert manager.started == original
    body.composition.scenes[0].title = "Different operation"
    with pytest.raises(ValueError, match="identity changed"):
        runtime.start(manager, body)


def test_missing_process_ack_requires_inspection_instead_of_launch(tmp_path):
    body = request()
    saved(tmp_path, body)
    with pytest.raises(ValueError, match="existing motion launch"):
        runtime.start(Manager(tmp_path), body)


def test_native_recovery_retains_budget_until_container_cleanup(tmp_path, monkeypatch):
    rid = str(uuid4())
    manager = ProcessManager(tmp_path, grace_seconds=0.1)
    monkeypatch.setattr(owner, "stop", lambda root, identity, **kw: False)
    manager.start(
        run_id=rid,
        argv=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        executor="motion_render",
        deadline_at=time.time() + 60,
    )
    for _ in range(100):
        state = manager.inspect(rid)
        if not state["alive"] and not state["completion_pending"]:
            break
        time.sleep(0.02)
    assert state["status"] == "interrupted" and state["cleanup_confirmed"] is False
    restored = ProcessManager(tmp_path)
    assert restored.inspect(rid)["cleanup_confirmed"] is False
    seen = []
    monkeypatch.setattr(owner, "stop", lambda root, identity, **kw: seen.append((root, identity, kw)) or True)
    assert restored.inspect(rid)["cleanup_confirmed"] is True
    restored.cancel(rid)
    assert seen[-1] == (tmp_path, rid, {"cancel": True})


def test_readiness_without_explicit_installation_never_contacts_docker(tmp_path, monkeypatch):
    from ai_station_runner import motion_image

    monkeypatch.setattr(motion_image, "connection", lambda: pytest.fail("No automatic daemon/model access"))
    with pytest.raises(ValueError, match="Prepare"):
        motion_image.image(SimpleNamespace(motion_image="", host_data_dir=lambda: tmp_path))


def test_cancel_before_delayed_dispatch_fences_even_missing_ownership(tmp_path):
    body = request()
    assert owner.stop(tmp_path, str(body.run_id), cancel=True)
    assert not (owner.directory(tmp_path, str(body.run_id)) / "request.json").exists()
    with pytest.raises(InterruptedError, match="canceled before dispatch"):
        runtime.start(Manager(tmp_path), body)


def test_http_contract_rejects_unknown_html_commands_and_missing_permissions(monkeypatch):
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient

    seen = []
    monkeypatch.setattr(runtime, "start", lambda manager, body: seen.append(body) or {"pid": 123})
    with TestClient(app) as client:
        valid = request().model_dump(mode="json")
        for extra in [{"html": "<script>"}, {"command": ["sh"]}, {"permissions": []}]:
            assert client.post("/v1/runs/motion", json={**valid, **extra}).status_code == 422
        assert not seen
        assert client.post("/v1/runs/motion", json=valid).status_code == 200
        assert len(seen) == 1
        assert (
            client.post(
                "/v1/motion/" + str(uuid4()) + "/cancel", json={"permissions": ["filesystem_read"]}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/motion/" + str(uuid4()) + "/cancel",
                json={"permissions": ["filesystem_read", "filesystem_read"]},
            ).status_code
            == 403
        )


def test_dead_process_cleanup_removes_only_its_staging_after_confirmation(tmp_path, monkeypatch):
    body = request()
    folder, _ = saved(tmp_path, body)
    work = folder / "work"
    work.mkdir()
    (work / "scratch").write_text("temporary frames")
    monkeypatch.setattr(owner, "stop", lambda *a, **k: False)
    assert owner.cleanup(tmp_path, str(body.run_id)) is False
    assert work.exists()
    monkeypatch.setattr(owner, "stop", lambda *a, **k: True)
    assert owner.cleanup(tmp_path, str(body.run_id))
    assert not work.exists() and (folder / "request.json").exists()
    outside = tmp_path / "other-material"
    outside.mkdir()
    (outside / "keep").write_text("owned elsewhere")
    work.symlink_to(outside)
    with pytest.raises(ValueError, match="staging ownership"):
        owner.cleanup(tmp_path, str(body.run_id))
    assert (outside / "keep").read_text() == "owned elsewhere"
