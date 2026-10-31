"""Container identity, crash recovery and publication without Docker or GPU use."""

import hashlib
import io
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from ai_station_runner import managed_image_job as job
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.managed_image_command import ImageCommand
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError


def frame(text, stream=1):
    data = text.encode()
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


def upscale_request(setup, format="PNG", corrupt=False, size=(256, 256)):
    root, _, _, original = setup
    source = root / "artifacts/source.png"
    source.parent.mkdir(exist_ok=True)
    output = io.BytesIO()
    Image.new("RGB", size, "blue").save(output, format=format)
    data = b"not an image" if corrupt else output.getvalue()
    source.write_bytes(data)
    source.chmod(0o600)
    reference = dict(
        relative_path="artifacts/source.png", sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)
    )
    body = job.Start.model_validate(
        {
            **original.model_dump(mode="json"),
            "command": {"mode": "upscale", "reference_count": 1, "width": size[0] * 4, "height": size[1] * 4},
            "references": [reference],
        }
    )
    return body, source, data


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_upscale_normalizes_verified_reference_and_publishes_exact_4x_output(setup, format):
    root, _, state, _ = setup
    body, source, data = upscale_request(setup, format)
    assert job.start(body)["alive"]
    record = job.read(body.run_id)
    private = job.folder(body.run_id) / "input-0.png"
    with Image.open(private) as image:
        assert image.format == "PNG" and image.size == (256, 256)
    assert source.read_bytes() == data and not private.stat().st_mode & 0o222
    argv = record["create"]["Cmd"]
    assert argv[argv.index("--upscale-model") + 1] == "/models/upscaler.pth"
    state["container"]["State"].update(Status="exited", Running=False, ExitCode=0, Pid=0)
    output = job.folder(body.run_id) / "output/result.png"
    Image.new("RGB", (1024, 1024), "blue").save(output)
    output.chmod(0o600)
    assert job.inspect(body.run_id)["exit_code"] == 0
    assert (root / job.read(body.run_id)["output"]["relative_path"]).is_file()


@pytest.mark.parametrize("corrupt,wrong_scale", [(True, False), (False, True)])
def test_upscale_rejects_invalid_source_or_wrong_scale_before_container_creation(setup, corrupt, wrong_scale):
    _, _, state, _ = setup
    body, _, _ = upscale_request(setup, corrupt=corrupt)
    if wrong_scale:
        body = body.model_copy(update={"command": body.command.model_copy(update={"width": 512})})
    with pytest.raises(HTTPException) as rejected:
        job.start(body)
    assert rejected.value.status_code == (422 if corrupt else 409)
    assert state["create_count"] == state["start_count"] == 0


def test_edit_resizes_only_its_private_copy_to_frozen_processing_geometry(setup):
    body, source, original = upscale_request(setup, size=(1024, 768))
    body = body.model_copy(
        update={
            "command": ImageCommand(
                mode="img2img",
                reference_count=1,
                width=512,
                height=384,
                prompt="Remove the red cup",
                steps=4,
                cfg=6.0,
                seed=42,
            )
        }
    )
    assert job.start(body)["alive"]
    with Image.open(job.folder(body.run_id) / "input-0.png") as image:
        assert image.size == (512, 384)
    assert source.read_bytes() == original


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    clear_settings_cache()
    monkeypatch.setattr(job, "QUALIFIED", True)
    root = tmp_path / "models/store"
    root.mkdir(parents=True)
    inputs = []
    for role in ["diffusion", "text_encoder", "vision_projector", "vae", "upscaler"]:
        data = ("GGUF " + role).encode()
        sha = hashlib.sha256(data).hexdigest()
        (root / sha).write_bytes(data)
        (root / sha).chmod(0o444)
        inputs.append(dict(role=role, sha256=sha, size_bytes=len(data)))
    frozen = dict(
        profile=job.PROFILE,
        qualified=True,
        files=inputs,
        runtime=dict(image_reference="ghcr.io/leejet/stable-diffusion.cpp@sha256:" + "a" * 64),
    )
    monkeypatch.setattr(job, "recipe", lambda: frozen)
    monkeypatch.setattr(job, "collect", lambda _: {"gpus": [{"index": 7, "uuid": "GPU-qa-seven"}]})
    daemon = dict(socket="/fake/docker.sock", id="fake-daemon", api_version="1.52")
    monkeypatch.setattr(job.runtime_install, "daemon", lambda: daemon)
    state = dict(
        container=None,
        calls=[],
        logs=frame("loading\n"),
        at_create=None,
        at_start=None,
        daemon_id="fake-daemon",
        create_count=0,
        start_count=0,
        stop_count=0,
        kill_count=0,
    )

    def docker(request):
        state["calls"].append((request.method, request.url.path))
        path = request.url.path
        if path == "/info":
            return httpx.Response(200, json={"ID": state["daemon_id"]})
        if path.startswith("/images/"):
            return httpx.Response(
                200,
                json=dict(
                    Os="linux",
                    Architecture="amd64",
                    Id="sha256:" + "b" * 64,
                    RepoDigests=[frozen["runtime"]["image_reference"]],
                ),
            )
        if path.endswith("/containers/create"):
            config = json.loads(request.content)
            state["create_count"] += 1
            if state.get("create_rejected"):
                return httpx.Response(500, text="fixture create rejected before any container exists")
            state["container"] = dict(
                Id="c" * 64,
                Image=config["Image"],
                Config={**config, "Labels": {**config["Labels"], "upstream.license": "MIT"}},
                HostConfig=config["HostConfig"],
                Mounts=[
                    dict(Source=m["Source"], Destination=m["Target"], RW=not m["ReadOnly"])
                    for m in config["HostConfig"]["Mounts"]
                ],
                State=dict(Status="created", Running=False, Pid=0, ExitCode=0),
            )
            if state["at_create"]:
                state["at_create"]()
            return httpx.Response(201, json={"Id": "c" * 64})
        if path.endswith("/json"):
            return httpx.Response(200, json=state["container"]) if state["container"] else httpx.Response(404)
        if request.method == "DELETE":
            assert request.url.params["v"] == "false"
            state["container"] = None
            return httpx.Response(204)
        if path.endswith("/start"):
            state["start_count"] += 1
            state["container"]["State"].update(Status="running", Running=True, Pid=12345)
            if state["at_start"]:
                state["at_start"]()
            return httpx.Response(204)
        if path.endswith("/stop") or path.endswith("/kill"):
            state["stop_count" if path.endswith("/stop") else "kill_count"] += 1
            if path.endswith("/stop") and state.get("stop_fails"):
                return httpx.Response(500)
            state["container"]["State"].update(Status="exited", Running=False, ExitCode=137, Pid=0)
            return httpx.Response(204)
        if path.endswith("/logs"):
            return httpx.Response(200, content=state["logs"])
        raise AssertionError((request.method, path))

    monkeypatch.setattr(
        job.runtime_install,
        "client",
        lambda _: httpx.Client(transport=httpx.MockTransport(docker), base_url="http://docker"),
    )
    body = job.Start(
        run_id=uuid4(),
        profile=job.PROFILE,
        manifest_sha256=job.fingerprint(frozen),
        command=ImageCommand(
            mode="t2i", prompt="A red mug", width=512, height=512, steps=4, cfg=5.0, seed=42
        ),
        gpus=[7],
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        permissions=sorted(job.PERMISSIONS),
    )
    yield tmp_path, frozen, state, body
    clear_settings_cache()


def finish(setup, *, exit_code=0, valid=True):
    _, _, state, body = setup
    state["container"]["State"].update(Status="exited", Running=False, ExitCode=exit_code, Pid=0)
    output = job.folder(body.run_id) / "output/result.png"
    if valid:
        Image.new("RGB", (512, 512), "red").save(output)
    else:
        output.write_bytes(b"partial image")
    output.chmod(0o600)


def test_actual_container_identity_is_frozen_hardened_and_repeated_start_only_inspects(setup):
    _, _, state, body = setup
    first = job.start(body)
    assert first["alive"] and first["executor"] == "photo_pipe" and first["execution_target"] == "container"
    assert job.start(body)["pid"] == first["pid"]
    assert state["create_count"] == state["start_count"] == 1
    record = job.read(body.run_id)
    assert record["container_id"] == "c" * 64 and record["start_attempted"]
    config = record["create"]
    assert config["Entrypoint"] == ["/bin/sh", "/station/deadline.sh"]
    assert config["Cmd"][:2] == [str(int(body.deadline_at.timestamp())), "/sd-cli"]
    assert config["HostConfig"]["Memory"] == config["HostConfig"]["MemorySwap"] == job.RAM
    assert config["HostConfig"]["NetworkMode"] == "none" and config["HostConfig"]["ReadonlyRootfs"]
    assert [m["Target"] for m in config["HostConfig"]["Mounts"] if not m["ReadOnly"]] == ["/output"]
    assert config["HostConfig"]["DeviceRequests"][0]["DeviceIDs"] == ["GPU-qa-seven"]


def test_rejected_create_can_be_stopped_without_stranding_reservations_or_allowing_a_late_start(setup):
    _, _, state, body = setup
    state["create_rejected"] = True
    with pytest.raises(httpx.HTTPStatusError):
        job.start(body)
    result = job.cancel(body.run_id, permissions=body.permissions)
    assert result["status"] == "canceled" and result["alive"] is False
    assert job.inspect(body.run_id)["status"] == "canceled"
    assert job.start(body)["status"] == "canceled"
    assert state["start_count"] == 0 and state["create_count"] == 1
    # A Docker create may have been queued before the failed response. Even
    # when it appears later, the durable Stop must never authorize its start.
    record = job.read(body.run_id)
    state["create_rejected"] = False
    with job.api_for(record) as api:
        reply = api.post("/v1.52/containers/create", params={"name": record["name"]}, json=record["create"])
        reply.raise_for_status()
    assert job.start(body)["status"] == "canceled" and state["start_count"] == 0
    assert job.cancel(body.run_id, permissions=body.permissions)["status"] == "canceled"
    assert state["container"] is None


def test_completed_png_publishes_once_and_retains_exact_prompt_and_source_identity(setup, monkeypatch):
    root, _, state, body = setup
    job.start(body)
    finish(setup)
    first = job.inspect(body.run_id)
    assert first["exit_code"] == 0 and not first["alive"]
    saved = job.read(body.run_id)
    output = root / saved["output"]["relative_path"]
    assert output.is_file() and hashlib.sha256(output.read_bytes()).hexdigest() == saved["output"]["sha256"]
    assert not (job.folder(body.run_id) / "output/result.png").exists()
    monkeypatch.setattr(job, "recipe", lambda: {"qualified": False})
    assert job.start(body)["exit_code"] == 0
    assert state["create_count"] == state["start_count"] == 1
    assert job.read(body.run_id)["request"]["command"]["prompt"] == body.command.prompt
    with pytest.raises(HTTPException):
        job.start(body.model_copy(update={"deadline_at": body.deadline_at + timedelta(minutes=1)}))


@pytest.mark.parametrize("stage", ["create", "start"])
def test_lost_acknowledgement_after_acceptance_never_starts_a_second_container(setup, stage):
    _, _, state, body = setup

    def lost():
        raise httpx.ReadTimeout("synthetic lost response")

    state["at_" + stage] = lost
    with pytest.raises(httpx.ReadTimeout):
        job.start(body)
    state["at_" + stage] = None
    assert job.start(body)["alive"]
    assert state["create_count"] == state["start_count"] == 1


def test_pre_dispatch_stop_tombstone_prevents_late_create(setup):
    _, _, state, body = setup
    stopped = job.cancel(body.run_id, permissions=body.permissions)
    assert not stopped["alive"] and stopped["status"] == "canceled"
    assert job.start(body)["status"] == "canceled"
    assert state["create_count"] == state["start_count"] == 0


def test_stop_after_client_loss_signals_only_the_verified_owned_container(setup):
    _, _, state, body = setup
    job.start(body)
    # No live client or process manager is needed to recover this durable record.
    assert job.inspect(body.run_id)["alive"]
    assert job.cancel(body.run_id, permissions=body.permissions)["status"] == "canceled"
    assert state["stop_count"] == 1 and not state["kill_count"]
    assert job.start(body)["status"] == "canceled" and state["start_count"] == 1


@pytest.mark.parametrize(
    "change", ["container_id", "labels", "image", "mount", "user", "network", "gpu", "command"]
)
def test_changed_container_cannot_be_adopted_or_signaled(setup, change):
    _, _, state, body = setup
    job.start(body)
    container = state["container"]
    if change == "container_id":
        container["Id"] = "d" * 64
    elif change == "labels":
        container["Config"]["Labels"]["ai-station.image.request"] = "other"
    elif change == "image":
        container["Image"] = "sha256:" + "d" * 64
    elif change == "mount":
        container["Mounts"][0]["Source"] = "/etc/passwd"
    elif change == "user":
        container["Config"]["User"] = "0:0"
    elif change == "network":
        container["HostConfig"]["NetworkMode"] = "host"
    elif change == "gpu":
        container["HostConfig"]["DeviceRequests"] = []
    elif change == "command":
        container["Config"]["Cmd"] = ["id"]
    with pytest.raises(HTTPException):
        job.inspect(body.run_id)
    with pytest.raises(HTTPException):
        job.cancel(body.run_id, permissions=body.permissions)
    assert state["stop_count"] == state["kill_count"] == 0


def test_changed_daemon_cannot_be_used_for_create_inspection_or_stop(setup):
    _, _, state, body = setup
    job.start(body)
    state["daemon_id"] = "another-daemon"
    with pytest.raises(HTTPException):
        job.inspect(body.run_id)
    with pytest.raises(HTTPException):
        job.cancel(body.run_id, permissions=body.permissions)
    assert not state["stop_count"]


def test_missing_container_after_dispatch_requires_inspection_never_reexecution(setup):
    _, _, state, body = setup
    job.start(body)
    state["container"] = None
    with pytest.raises(HTTPException):
        job.start(body)
    with pytest.raises(HTTPException):
        job.inspect(body.run_id)
    with pytest.raises(HTTPException):
        job.cancel(body.run_id, permissions=body.permissions)
    assert state["create_count"] == state["start_count"] == 1


@pytest.mark.parametrize("exit_code,valid", [(0, False), (1, True), (137, False)])
def test_failed_or_partial_output_never_publishes_a_success_artifact(setup, exit_code, valid):
    root, _, _, body = setup
    job.start(body)
    finish(setup, exit_code=exit_code, valid=valid)
    result = job.inspect(body.run_id)
    assert not result["alive"] and result["exit_code"] != 0
    assert not job.read(body.run_id).get("output")
    assert not list((root / "artifacts").rglob("*.png"))


def test_read_offsets_are_bounded_and_replay_does_not_repeat_bytes(setup):
    _, _, state, body = setup
    state["logs"] = frame("a" * 70000) + frame("a warning", 2)
    first = job.start(body)
    second = job.inspect(
        body.run_id, stdout_offset=first["stdout_offset"], stderr_offset=first["stderr_offset"]
    )
    assert len(first["stdout"]) == 65536 and first["stdout_more"]
    assert first["stdout"] + second["stdout"] == "a" * 70000
    assert second["stderr"] == "" and not second["stdout_more"]
    with pytest.raises(HTTPException):
        job.inspect(body.run_id, stdout_offset=-1)


@pytest.mark.parametrize("writable", [True, False])
def test_model_changed_between_create_and_start_never_runs(setup, writable):
    root, frozen, state, body = setup
    model = root / "models/store" / frozen["files"][0]["sha256"]

    def change():
        if writable:
            model.chmod(0o600)
        else:
            other = root / "other"
            other.write_bytes(b"changed")
            model.unlink()
            model.symlink_to(other)

    state["at_create"] = change
    with pytest.raises(HTTPException):
        job.start(body)
    assert state["start_count"] == 0


def test_unqualified_profile_rejects_start_before_docker_access(setup, monkeypatch):
    _, frozen, state, body = setup
    monkeypatch.setattr(job, "QUALIFIED", False)
    with pytest.raises(HTTPException):
        job.start(body)
    assert not state["calls"]


def test_in_container_guard_honors_absolute_deadline_and_terminates_its_child(tmp_path):
    guard = tmp_path / "guard.sh"
    cgroup = tmp_path / "fake-cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(job.RAM))
    (cgroup / "memory.swap.max").write_text("0")
    guard.write_bytes(job.GUARD.replace(b"/sys/fs/cgroup/", str(cgroup).encode() + b"/"))
    started = time.monotonic()
    result = subprocess.run(
        [
            "/bin/sh",
            str(guard),
            str(int(time.time()) + 2),
            sys.executable,
            "-c",
            "import time;time.sleep(30)",
        ],
        timeout=6,
    )
    assert result.returncode == 124 and time.monotonic() - started < 5
    marker = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            "/bin/sh",
            str(guard),
            "1",
            sys.executable,
            "-c",
            f"from pathlib import Path;Path({str(marker)!r}).touch()",
        ],
        timeout=2,
    )
    assert result.returncode == 124 and not marker.exists()


@pytest.mark.parametrize("gpus", [[True], ["7"], [7, 7], [-1]])
def test_gpu_selection_is_structured_and_strict(setup, gpus):
    _, _, _, body = setup
    with pytest.raises(ValidationError):
        job.Start(**{**body.model_dump(), "gpus": gpus})


def test_start_not_yet_accepted_is_pending_until_owned_deletion_fences_the_late_request(setup):
    _, _, state, body = setup

    def lost_before_acceptance():
        state["container"]["State"].update(Status="created", Running=False, Pid=0)
        raise httpx.ReadTimeout("start acknowledgement remains uncertain")

    state["at_start"] = lost_before_acceptance
    with pytest.raises(httpx.ReadTimeout):
        job.start(body)
    observed = job.inspect(body.run_id)
    assert observed["completion_pending"] and observed["exit_code"] is None
    assert job.start(body)["completion_pending"] and state["start_count"] == 1
    assert job.cancel(body.run_id, permissions=body.permissions)["status"] == "canceled"
    assert job.read(body.run_id)["removed_after_cancel"] and state["container"] is None
    assert job.start(body)["status"] == "canceled"
    assert job.inspect(body.run_id)["status"] == "canceled"
    assert job.cancel(body.run_id, permissions=body.permissions)["status"] == "canceled"
    assert state["create_count"] == state["start_count"] == 1


def test_deleted_published_image_is_not_restored_from_a_shadow_copy(setup):
    root, _, _, body = setup
    job.start(body)
    finish(setup)
    assert job.inspect(body.run_id)["exit_code"] == 0
    output = root / job.read(body.run_id)["output"]["relative_path"]
    output.unlink()
    assert job.inspect(body.run_id)["exit_code"] != 0
    assert not output.exists() and not (job.folder(body.run_id) / "output/result.png").exists()


def test_failed_graceful_stop_uses_kill_only_after_fresh_owned_inspection(setup):
    _, _, state, body = setup
    job.start(body)
    state["stop_fails"] = True
    result = job.cancel(body.run_id, permissions=body.permissions)
    assert not result["alive"] and result["status"] == "canceled"
    assert state["stop_count"] == state["kill_count"] == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_unreadable_logs_never_publish_success_or_prevent_confirmed_cancellation(setup, cancel):
    root, _, state, body = setup
    job.start(body)
    state["logs"] = b"broken multiplex header"
    if cancel:
        result = job.cancel(body.run_id, permissions=body.permissions)
        assert result["status"] == "canceled" and not result["alive"]
    else:
        finish(setup)
        result = job.inspect(body.run_id)
        assert not result["alive"] and result["exit_code"] != 0
    assert job.read(body.run_id)["logs_unavailable"]
    assert not job.read(body.run_id).get("output")
    assert not list((root / "artifacts").rglob("*.png"))


def test_unverified_memory_or_swap_limits_refuse_to_launch_child(tmp_path):
    cgroup = tmp_path / "fake-cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text("max")
    (cgroup / "memory.swap.max").write_text("0")
    guard = tmp_path / "guard.sh"
    guard.write_bytes(job.GUARD.replace(b"/sys/fs/cgroup/", str(cgroup).encode() + b"/"))
    marker = tmp_path / "not-launched"
    result = subprocess.run(
        [
            "/bin/sh",
            str(guard),
            str(int(time.time()) + 30),
            sys.executable,
            "-c",
            f"from pathlib import Path;Path({str(marker)!r}).touch()",
        ],
        timeout=3,
    )
    assert result.returncode == 125 and not marker.exists()


def test_transient_log_failure_preserves_prior_bytes_and_can_recover_before_completion(setup):
    _, _, state, body = setup
    first = job.start(body)
    assert first["stdout"] == "loading\n"
    state["logs"] = b"broken multiplex header"
    interim = job.inspect(body.run_id, stdout_offset=first["stdout_offset"])
    assert interim["alive"] and interim["stdout"] == ""
    assert (job.folder(body.run_id) / "stdout.log").read_text() == "loading\n"
    state["logs"] = frame("loading\nfinished\n")
    finish(setup)
    final = job.inspect(body.run_id, stdout_offset=first["stdout_offset"])
    assert final["exit_code"] == 0 and final["stdout"] == "finished\n"
    assert not job.read(body.run_id)["logs_unavailable"]


@pytest.mark.parametrize("change", ["command", "mount", "entrypoint", "context", "labels"])
def test_edited_shared_journal_cannot_authorize_new_commands_mounts_or_a_docker_context(setup, change):
    _, _, state, body = setup

    def lost_create():
        state["container"] = None
        raise httpx.ReadTimeout("unconfirmed create; no start was attempted")

    state["at_create"] = lost_create
    with pytest.raises(httpx.ReadTimeout):
        job.start(body)
    state["at_create"] = None
    record = job.read(body.run_id)
    if change == "command":
        record["create"]["Cmd"] = ["/bin/sh", "-c", "unreviewed code"]
    elif change == "mount":
        record["create"]["HostConfig"]["Mounts"][0]["Source"] = "/"
    elif change == "entrypoint":
        record["create"]["Entrypoint"] = ["/bin/sh", "-c"]
    elif change == "context":
        record["daemon"]["socket"] = "/unreviewed/docker.sock"
    else:
        record["create"]["Labels"] = {}
    job.save(body.run_id, record)
    with pytest.raises(HTTPException):
        job.start(body)
    assert state["create_count"] == 1 and state["start_count"] == 0


def test_guard_code_is_packaged_outside_shared_application_storage(setup):
    root, _, _, body = setup
    job.start(body)
    mounts = job.read(body.run_id)["create"]["HostConfig"]["Mounts"]
    guard = next(m for m in mounts if m["Target"] == "/station/deadline.sh")
    assert guard["ReadOnly"] and guard["Source"] == str(job.GUARD_PATH)
    assert not job.GUARD_PATH.is_relative_to(root)
