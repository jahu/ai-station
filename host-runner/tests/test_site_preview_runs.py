import hashlib
import io
import json
import stat
import sys
import time
import zipfile
from uuid import uuid4

import pytest
from ai_station_runner import site_preview_runs as preview
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from ai_station_runner.site_preview_source import BuildSource
from fastapi.testclient import TestClient

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64


@pytest.fixture(autouse=True)
def environment(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_SITE_PREVIEW_IMAGE", "ai-station-site-preview:test")
    from ai_station_runner.app import reset_manager

    clear_settings_cache()
    reset_manager()
    yield
    reset_manager()
    clear_settings_cache()


def archive(entries=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as handle:
        for name, contents in entries or [
            ("index.html", b"<h1>Safe build</h1>"),
            ("app.js", b"export const n=1"),
        ]:
            handle.writestr(name, contents)
    value = data.getvalue()
    body = preview.Archive(
        artifact_id=uuid4(), sha256=hashlib.sha256(value).hexdigest(), size_bytes=len(value)
    )
    target = preview.owned_path(body.relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)
    return body, target


def request():
    source, _ = archive()
    return preview.PreviewRequest(
        run_id=uuid4(), archive=source, width=800, height=600, permissions=sorted(preview.PERMISSIONS)
    )


class Manager:
    def __init__(self):
        self.records = {}
        self.calls = []

    def inspect(self, run_id):
        if run_id not in self.records:
            raise ProcessNotOwned(run_id)
        return self.records[run_id]

    def start(self, **kwargs):
        self.calls.append(kwargs)
        value = {"executor": kwargs["executor"], "pid": 12, "alive": True, "status": "running"}
        self.records[kwargs["run_id"]] = value
        return value


def started(monkeypatch):
    monkeypatch.setattr(preview, "capabilities", lambda: {"available": True, "image_id": IMAGE})
    manager, body = Manager(), request()
    preview.start_preview(manager, body)
    return manager, body


def frame(body, revision=0, action_id=None):
    return {
        "revision": revision,
        "action_id": action_id,
        "width": body.width,
        "height": body.height,
        "path": "index.html",
        "title": "Local site",
        "blocked_requests": 0,
        "relative_path": f"runtime/site-previews/{body.run_id}/frames/{revision}.png",
        "sha256": "a" * 64,
        "size_bytes": 1,
    }


def ready(monkeypatch):
    manager, body = started(monkeypatch)
    preview.save(
        preview.path(body.run_id, "state.json"),
        {"request_digest": preview.digest(body), "frame": frame(body)},
    )
    return manager, body


def action(body, **changes):
    return preview.PreviewAction(
        run_id=uuid4(),
        preview_run_id=body.run_id,
        expected_revision=0,
        action={"kind": "click", "x": 20, "y": 30},
        permissions=sorted(preview.PERMISSIONS),
        **changes,
    )


def container(saved):
    name, labels = preview.container_identity(saved)
    return {"Id": CID, "Name": "/" + name, "Image": IMAGE, "Config": {"Labels": labels}}


def test_native_schema_permissions_and_no_arbitrary_command_or_url():
    from ai_station_runner.app import app

    client = TestClient(app)
    body = request().model_dump(mode="json")
    for changes in (
        {"command": "sh"},
        {"url": "http://127.0.0.1/"},
        {"width": True},
        {"entry": "../secret.html"},
        {"permissions": ["x" * 100]},
    ):
        assert client.post("/v1/runs/site-preview", json={**body, **changes}).status_code == 422
    assert (
        client.post("/v1/runs/site-preview", json={**body, "permissions": ["filesystem_read"]}).status_code
        == 403
    )
    interaction = action(preview.PreviewRequest.model_validate(body)).model_dump(mode="json")
    assert (
        client.post("/v1/runs/site-preview-action", json={**interaction, "permissions": []}).status_code
        == 403
    )
    for value in (
        {"kind": "evaluate", "script": "alert(1)"},
        {"kind": "click", "x": -1, "y": 0},
        {"kind": "key", "key": "Control+L"},
    ):
        assert (
            client.post("/v1/runs/site-preview-action", json={**interaction, "action": value}).status_code
            == 422
        )


def test_capability_requires_exact_installed_nonroot_image_protocol(monkeypatch):
    image = {
        "Id": IMAGE,
        "Config": {
            "Entrypoint": preview.ENTRYPOINT,
            "User": "1000:1000",
            "Labels": {"ai-station.site-preview.protocol": "2"},
        },
    }
    monkeypatch.setattr(preview, "docker", lambda *args, **kwargs: json.dumps(image))
    assert preview.capabilities()["available"] and preview.capabilities()["network"] is False
    image["Config"]["Entrypoint"] = ["sh"]
    assert not preview.capabilities()["available"]
    image["Config"]["Entrypoint"] = preview.ENTRYPOINT
    image["Config"]["User"] = "root"
    assert not preview.capabilities()["available"]


def test_dispatch_replay_uses_same_registered_owner_and_never_restarts(monkeypatch):
    manager, body = started(monkeypatch)
    assert preview.start_preview(manager, body)["pid"] == 12 and len(manager.calls) == 1
    assert manager.calls[0]["argv"][1:3] == ["-m", "ai_station_runner.site_preview_job"]
    with pytest.raises(ValueError, match="another"):
        preview.start_preview(manager, body.model_copy(update={"height": 700}))
    manager.records.clear()
    with pytest.raises(ValueError, match="inspection"):
        preview.start_preview(manager, body)
    assert len(manager.calls) == 1


def test_single_native_session_admission_survives_uncertain_dispatch(monkeypatch):
    manager, body = started(monkeypatch)
    other = request()
    with pytest.raises(ValueError, match="active"):
        preview.start_preview(manager, other)
    manager.records.clear()
    with pytest.raises(ValueError, match="inspection"):
        preview.start_preview(manager, other)
    assert preview.cancel_preview(str(body.run_id))  # No create manifest and cancel barrier is persisted.
    preview.start_preview(manager, other)
    assert len(manager.calls) == 2


def test_native_rechecks_frozen_archive_bytes_and_symlink_boundary(monkeypatch):
    monkeypatch.setattr(preview, "capabilities", lambda: {"available": True, "image_id": IMAGE})
    body = request()
    preview.owned_path(body.archive.relative_path).write_bytes(b"changed")
    with pytest.raises(ValueError):
        preview.start_preview(Manager(), body)
    body = request()
    target = preview.owned_path(body.archive.relative_path)
    contents = target.read_bytes()
    target.unlink()
    outside = target.parent.parent.parent.parent.parent / "external.zip"
    outside.write_bytes(contents)
    target.symlink_to(outside)
    with pytest.raises((ValueError, RuntimeError, GitError)):
        preview.start_preview(Manager(), body)


def test_native_action_freezes_viewport_receipt_and_parent_identity(monkeypatch):
    manager, body = ready(monkeypatch)
    value = action(body)
    preview.start_action(manager, value)
    assert (
        preview.start_action(manager, value)["executor"] == "site_preview_action" and len(manager.calls) == 2
    )
    assert manager.calls[-1]["argv"][1:3] == ["-m", "ai_station_runner.site_preview_action_job"]
    with pytest.raises(ValueError, match="another"):
        preview.start_action(manager, value.model_copy(update={"action": {"kind": "snapshot"}}))
    with pytest.raises(ValueError, match="invalid"):
        preview.start_action(
            manager, action(body).model_copy(update={"action": {"kind": "click", "x": 1000, "y": 0}})
        )
    with pytest.raises(ValueError, match="changed"):
        preview.start_action(manager, action(body).model_copy(update={"expected_revision": 1}))
    assert len(manager.calls) == 2


@pytest.mark.parametrize("tamper", ["id", "image", "label", "name"])
def test_cleanup_never_removes_another_container(monkeypatch, tamper):
    _, body = started(monkeypatch)
    saved = preview.load_request(str(body.run_id))
    preview.save(preview.path(body.run_id, "container.json"), {"state": "created", "id": CID})
    value = container(saved)
    if tamper == "id":
        value["Id"] = "c" * 64
    if tamper == "image":
        value["Image"] = "sha256:" + "c" * 64
    if tamper == "name":
        value["Name"] = "/unrelated"
    if tamper == "label":
        value["Config"]["Labels"]["ai-station.site-preview.owner"] = str(uuid4())
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return json.dumps(value)

    monkeypatch.setattr(preview, "docker", docker)
    with pytest.raises(ValueError, match="ownership"):
        preview.cancel_preview(str(body.run_id))
    assert not any(args[0] == "rm" for args in calls)


def test_unknown_create_cannot_claim_cleanup_or_release_the_native_slot(monkeypatch):
    manager, body = started(monkeypatch)
    preview.save(preview.path(body.run_id, "container.json"), {"state": "creating", "id": None})
    monkeypatch.setattr(preview, "docker", lambda *args, **kwargs: None)
    assert not preview.stop_container(str(body.run_id))
    manager.records[str(body.run_id)].update(alive=False, cleanup_confirmed=False)
    with pytest.raises(ValueError, match="inspection"):
        preview.start_preview(manager, request())


def test_cancel_before_send_is_noop_but_uncertain_send_closes_only_its_preview(monkeypatch):
    manager, body = ready(monkeypatch)
    value = action(body)
    preview.start_action(manager, value)
    assert preview.cancel_action(str(value.run_id))
    assert preview.action_result(str(value.run_id))["state"] == "canceled"
    assert not preview.path(body.run_id, "cancel.json").exists()
    manager.records[str(value.run_id)].update(alive=False, cleanup_confirmed=True)
    value = action(body)
    preview.start_action(manager, value)
    preview.save(
        preview.path(value.run_id, "receipt.json", action=True),
        {"state": "sent", "digest": preview.digest(value)},
    )
    assert preview.cancel_action(str(value.run_id))
    assert preview.path(body.run_id, "cancel.json").exists()


@pytest.mark.parametrize(
    "tamper",
    [
        {"relative_path": "../../secret.png"},
        {"width": True},
        {"revision": True},
        {"action_id": str(uuid4())},
        {"sha256": "bad"},
    ],
)
def test_frame_cannot_redirect_host_reads_or_change_capture_identity(monkeypatch, tamper):
    _, body = ready(monkeypatch)
    with pytest.raises(ValueError):
        preview.frame_metadata(str(body.run_id), {**frame(body), **tamper})


def test_proxy_exit_after_uncertain_send_cleans_only_the_owned_container(monkeypatch):
    manager, body = ready(monkeypatch)
    value = action(body)
    preview.start_action(manager, value)
    preview.save(
        preview.path(value.run_id, "receipt.json", action=True),
        {"state": "sent", "digest": preview.digest(value)},
    )
    saved = preview.load_request(str(body.run_id))
    preview.save(preview.path(body.run_id, "container.json"), {"state": "created", "id": CID})
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return json.dumps(container(saved)) if args[0] == "inspect" else ""

    monkeypatch.setattr(preview, "docker", docker)
    real = ProcessManager(preview.get_settings().host_data_dir(), grace_seconds=0.01)
    rid = str(value.run_id)
    real.start(
        run_id=rid,
        argv=[sys.executable, "-c", "pass"],
        cwd=preview.get_settings().host_data_dir(),
        executor="site_preview_action",
    )
    deadline = time.monotonic() + 3
    while True:
        record = real.inspect(rid)
        if not record["alive"] and not record["completion_pending"]:
            break
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert record["cleanup_confirmed"] and ["rm", "--force", CID] in calls
    assert preview.path(body.run_id, "cancel.json").exists()


def test_static_broker_serves_modules_and_spa_navigation_without_fake_api_data():
    body, filename = archive()
    broker = BuildSource(filename, body.sha256, body.size_bytes)
    assert broker.resource("app.js") == (200, "text/javascript", b"export const n=1")
    assert broker.resource("contacts", document=True)[0] == 200
    assert broker.resource("api/quotes")[0] == 404
    with pytest.raises(ValueError):
        broker.resource("../secret")


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a//b", ".env", "index.html/"])
def test_static_broker_rejects_unsafe_zip_members(name):
    body, filename = archive([("index.html", b"ok"), (name, b"unsafe")])
    with pytest.raises(ValueError):
        BuildSource(filename, body.sha256, body.size_bytes)


def test_static_broker_rejects_symlinks_duplicates_and_missing_entry():
    symlink = zipfile.ZipInfo("link")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    for entries in (
        [("index.html", b"ok"), (symlink, b"/etc/passwd")],
        [("index.html", b"a"), ("index.html", b"b")],
        [("app.js", b"no entry")],
    ):
        body, filename = archive(entries)
        with pytest.raises(ValueError):
            BuildSource(filename, body.sha256, body.size_bytes)


def test_pending_atomic_mailbox_file_is_not_a_committed_action(monkeypatch):
    from ai_station_runner.site_preview_job import next_action

    _, body = ready(monkeypatch)
    queue = preview.path(body.run_id, "queue")
    queue.mkdir()
    (queue / ".preview-partial").write_text("not a committed JSON action")
    assert next_action(str(body.run_id), preview.load_request(str(body.run_id)), 0) is None


def test_close_can_reconcile_a_failed_dispatch_without_reexecuting_it(monkeypatch):
    manager, body = started(monkeypatch)
    manager.records.clear()
    assert preview.close_preview(manager, str(body.run_id))["cleanup_confirmed"]
    assert preview.path(body.run_id, "cancel.json").exists()
    assert len(manager.calls) == 1
    preview.save(preview.path(body.run_id, "container.json"), {"state": "creating", "id": None})
    monkeypatch.setattr(preview, "docker", lambda *args, **kwargs: None)
    assert not preview.close_preview(manager, str(body.run_id))["cleanup_confirmed"]


def test_container_creation_has_no_mounts_network_gpu_or_command_override(monkeypatch):
    from ai_station_runner import site_preview_job as job

    _, body = started(monkeypatch)
    saved = preview.load_request(str(body.run_id))
    commands = []

    def docker(args, **kwargs):
        commands.append(args)
        return CID if args[0] == "create" else json.dumps(container(saved))

    monkeypatch.setattr(job, "docker", docker)
    monkeypatch.setattr(preview, "docker", docker)
    assert job.create_container(str(body.run_id), saved) == CID
    create = commands[0]
    assert create[-1] == IMAGE
    for flag, expected in {
        "--network": "none",
        "--cap-drop": "ALL",
        "--memory": "1g",
        "--memory-swap": "1g",
        "--cpus": "1",
        "--pids-limit": "256",
        "--pull": "never",
    }.items():
        assert create[create.index(flag) + 1] == expected
    assert not set(create) & {"--privileged", "--mount", "--volume", "--gpus", "--entrypoint"}
    assert "--read-only" in create and "--init" in create


@pytest.mark.parametrize("created_at", [False, float("nan"), float("inf"), -1])
def test_deadline_journal_requires_a_finite_positive_time(monkeypatch, created_at):
    _, body = started(monkeypatch)
    saved = preview.load_request(str(body.run_id))
    preview.save(preview.path(body.run_id), {**saved, "created_at": created_at})
    with pytest.raises(ValueError, match="deadline"):
        preview.load_request(str(body.run_id))


def test_native_admission_bounds_action_proxies_per_preview(monkeypatch):
    manager, body = ready(monkeypatch)
    first = action(body)
    preview.start_action(manager, first)
    with pytest.raises(ValueError, match="active"):
        preview.start_action(manager, action(body))
    assert len(manager.calls) == 2
