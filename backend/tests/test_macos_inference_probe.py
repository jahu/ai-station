"""Probe protocol controls; native facts/SDK/inference are simulated, not Mac evidence."""

import asyncio
import hashlib
import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import macos_inference_probe as probe
import pytest


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    root = tmp_path / "probe-data"
    root.mkdir(mode=0o700)
    data = b"GGUF" + b"synthetic probe input"
    digest = hashlib.sha256(data).hexdigest()
    model = root / "models/store" / digest
    model.parent.mkdir(parents=True)
    model.write_bytes(data)
    model.chmod(0o444)
    state = {
        "root": root,
        "output": tmp_path / "proof",
        "digest": digest,
        "managers": [],
        "failure": None,
        "calls": [],
    }
    monkeypatch.setattr(
        probe,
        "platform",
        SimpleNamespace(
            system=lambda: "Darwin", machine=lambda: "arm64", mac_ver=lambda: ("14.0", None, None)
        ),
    )
    monkeypatch.setattr(probe.os, "geteuid", lambda: model.stat().st_uid)
    monkeypatch.setattr(
        probe.native,
        "inspect_context",
        lambda *a: {"source": "gguf_header", "q8_kv_bytes_per_token": 256, "trained_context": 131072},
    )
    monkeypatch.setattr(
        probe.native,
        "collect",
        lambda *a: {"metal": {"complete": True, "devices": [{"registry_id": "0000000000000123"}]}},
    )

    def prepare(root, operation, architecture, *, check, progress):
        state["calls"].append(("prepare", operation, architecture))
        check()
        progress({"phase": "preparing"})
        if state["failure"] == "prepare":
            raise ValueError("PRIVATE failure details must not be printed")
        # Same receipt keys as the actual assembler, no invented operation_id.
        return {"manifest_sha256": "a" * 64, "relative_path": "prepared", "inference_qualified": False}

    class Manager:
        def __init__(self, root, sockets):
            self.sockets = sockets
            self.closed = False
            self.stopped = False
            state["managers"].append(self)

        def load(self, body):
            state["calls"].append(("load", body))
            self.body = body
            if state["failure"] == "ack":
                raise OSError("PRIVATE lost acknowledgement")
            if state["failure"] == "replacement" and len(state["managers"]) == 2:
                return {"status": "ready", "pid": 99}
            return self.inspect(body.instance_id)

        def inspect(self, identity):
            if state["failure"] == "startup" and not self.stopped:
                return {
                    "status": "failed",
                    "alive": False,
                    "exit_code": 1,
                    "error": "Native llama.cpp process exited",
                    "stdout": "PRIVATE output",
                    "path": "/PRIVATE/data",
                }
            return {"status": "stopped" if self.stopped else "ready", "alive": not self.stopped, "pid": 37}

        async def completion(self, identity, body, incoming):
            assert body.messages[0].content == "Reply with the text MAC_NATIVE_OK."
            assert not await incoming.is_disconnected()
            state["calls"].append(("completion", identity))

            async def stream():
                if state["failure"] == "stream":
                    yield b'data: {"error":"PRIVATE upstream failure"}\n\n'
                else:
                    yield b'data: {"choices":[{"delta":{"content":"MAC_"}}]}\n\n'
                    yield b'data: {"choices":[{"delta":{"content":"NATIVE_OK"}}]}\n\n'
                    yield b"data: [DONE]\n\n"

            return SimpleNamespace(body_iterator=stream())

        def stop(self, identity, permissions):
            state["calls"].append(("stop", identity, permissions))
            if state["failure"] == "stop":
                return {"status": "inspection_required", "alive": None}
            self.stopped = True
            return self.inspect(identity)

        def close(self):
            self.closed = True

    monkeypatch.setattr(probe.native.bundle, "prepare", prepare)
    monkeypatch.setattr(probe.native, "NativeLlamaManager", Manager)
    state["run"] = lambda **kw: probe.run(
        root, state["output"], digest, kw.pop("compute", "cpu"), 4096, **({"opted_in": True} | kw)
    )
    return state


@pytest.mark.parametrize("compute", ["cpu", "metal"])
def test_probe_protocol_retains_same_instance_streams_twice_and_stops(fixture, compute):
    result = fixture["run"](compute=compute)
    assert result["status"] == "passed_native_probe_only" and result["owned_stop_confirmed"]
    assert result["native_inference_passed"] and result["observer_replacement"]
    assert not result["macos_installer_qualified"] and not result["cross_process_restart_tested"]
    assert (
        result["first_reply"]
        == result["retained_reply"]
        == {"characters": 13, "sha256": hashlib.sha256(b"MAC_NATIVE_OK").hexdigest()}
    )
    assert all(manager.closed for manager in fixture["managers"])
    assert not Path(result["socket_root"]).exists()
    loads = [call[1] for call in fixture["calls"] if call[0] == "load"]
    assert len(loads) == 2 and loads[0] == loads[1]
    assert loads[0].bundle_operation_id == fixture["calls"][0][1]
    proof = fixture["output"] / "proof.json"
    assert proof.stat().st_mode & 0o777 == 0o600
    assert "MAC_NATIVE_OK" not in proof.read_text()


@pytest.mark.parametrize("failure", ["prepare", "ack", "replacement", "stream", "stop"])
def test_failed_probe_never_reports_success_and_stops_only_its_instance(fixture, failure):
    fixture["failure"] = failure
    try:
        with pytest.raises((ValueError, RuntimeError, OSError)):
            fixture["run"]()
        result = json.loads((fixture["output"] / "proof.json").read_text())
        assert result["status"] in {"failed", "inspection_required"}
        assert "PRIVATE" not in json.dumps(result)
        assert not result["macos_installer_qualified"]
        if failure == "stop":
            assert not result["owned_stop_confirmed"] and Path(result["socket_root"]).exists()
        else:
            assert result["owned_stop_confirmed"]
        assert all(manager.closed for manager in fixture["managers"])
    finally:
        if failure == "stop":
            import shutil

            shutil.rmtree(result["socket_root"])


@pytest.mark.parametrize(
    "change", ["optout", "Linux", "root", "old", "architecture", "existing", "public", "intel_metal"]
)
def test_unqualified_or_existing_environment_cannot_start_native_probe(fixture, monkeypatch, change):
    kwargs = {}
    if change == "optout":
        kwargs["opted_in"] = False
    if change == "Linux":
        monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    if change == "root":
        monkeypatch.setattr(probe.os, "geteuid", lambda: 0)
    if change == "old":
        monkeypatch.setattr(probe.platform, "mac_ver", lambda: ("13.2", None, None))
    if change == "architecture":
        monkeypatch.setattr(probe.platform, "machine", lambda: "unknown")
    if change == "existing":
        (fixture["root"] / "runtime").mkdir()
    if change == "public":
        fixture["root"].chmod(0o755)
    if change == "intel_metal":
        monkeypatch.setattr(probe.platform, "machine", lambda: "x86_64")
        kwargs["compute"] = "metal"
    with pytest.raises((ValueError, RuntimeError)):
        fixture["run"](**kwargs)
    assert not fixture["calls"] and not fixture["output"].exists()


def test_existing_proof_is_never_overwritten(fixture):
    fixture["output"].mkdir(mode=0o700)
    marker = fixture["output"] / "retained"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        fixture["run"]()
    assert marker.read_text() == "keep" and not fixture["calls"]


def test_failed_startup_retains_only_safe_native_status_and_stops(fixture):
    fixture["failure"] = "startup"
    with pytest.raises(RuntimeError, match="inspection"):
        fixture["run"]()
    result = json.loads((fixture["output"] / "proof.json").read_text())
    assert result["native_failure"] == {
        "status": "failed",
        "alive": False,
        "exit_code": 1,
        "error": "Native llama.cpp process exited",
    }
    assert result["owned_stop_confirmed"] and "PRIVATE" not in json.dumps(result)


def test_wrong_model_hash_cannot_be_qualified_even_with_a_valid_owned_filename(fixture):
    model = fixture["root"] / "models/store" / fixture["digest"]
    model.chmod(0o644)
    model.write_bytes(model.read_bytes().replace(b"synthetic", b"different"))
    model.chmod(0o444)
    with pytest.raises(ValueError, match="hash"):
        fixture["run"]()
    assert not fixture["calls"] and not fixture["output"].exists()


def test_proof_claim_does_not_adopt_a_concurrently_created_runtime(fixture, monkeypatch):
    original = probe.atomic_json

    def concurrent(folder, filename, value):
        original(folder, filename, value)
        if value["status"] == "preparing":
            (fixture["root"] / "runtime").mkdir(mode=0o700)
            (fixture["root"] / "runtime/retain").write_text("other owner")

    monkeypatch.setattr(probe, "atomic_json", concurrent)
    with pytest.raises(FileExistsError):
        fixture["run"]()
    result = json.loads((fixture["output"] / "proof.json").read_text())
    assert result["status"] == "failed" and not fixture["calls"]
    assert (fixture["root"] / "runtime/retain").read_text() == "other owner"


def test_failed_socket_cleanup_retains_inspection_proof_without_false_success(fixture, monkeypatch):
    original = probe.shutil.rmtree

    def denied(*args):
        raise PermissionError("PRIVATE cleanup failure")

    try:
        with monkeypatch.context() as context:
            context.setattr(probe.shutil, "rmtree", denied)
            with pytest.raises(RuntimeError):
                fixture["run"]()
        result = json.loads((fixture["output"] / "proof.json").read_text())
        assert result["status"] == "inspection_required" and result["owned_stop_confirmed"]
        assert not result["socket_cleanup_confirmed"] and "PRIVATE" not in json.dumps(result)
    finally:
        original(result["socket_root"])


def test_stream_timeout_closes_the_upstream_iterator(monkeypatch):
    closed = []

    class Manager:
        async def completion(self, *args):
            async def stream():
                try:
                    yield b'data: {"choices":[]}\n\n'
                    await asyncio.sleep(60)
                finally:
                    closed.append(True)

            return SimpleNamespace(body_iterator=stream())

    wait_for = asyncio.wait_for
    monkeypatch.setattr(probe.asyncio, "wait_for", lambda task, timeout: wait_for(task, timeout=0.01))
    with pytest.raises(TimeoutError):
        asyncio.run(probe.reply(Manager(), "fixture"))
    assert closed == [True]


@pytest.mark.parametrize("interrupt", [False, True])
def test_cli_redacts_errors_and_restores_its_signal_handler(monkeypatch, capsys, interrupt):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--data-root",
            "/fixture",
            "--output",
            "/proof",
            "--model-sha256",
            "a" * 64,
            "--compute",
            "cpu",
        ],
    )
    previous = signal.getsignal(signal.SIGTERM)

    def fail(*args, **kwargs):
        if interrupt:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise OSError("PRIVATE uncontrolled failure")

    monkeypatch.setattr(probe, "run", fail)
    assert probe.main() == (130 if interrupt else 1)
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    assert json.loads(output.out)["status"] == ("interrupted" if interrupt else "failed")
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize(
    "payload",
    [b"data: [DONE]\n\n", b'data: {"choices":[]}\n\n', b"data: []\n\n", b"data: [DONE]\n\ndata: {}\n\n"],
)
def test_incomplete_or_invalid_stream_cannot_qualify_a_model(payload):
    class Manager:
        async def completion(self, *args):
            async def stream():
                yield payload

            return SimpleNamespace(body_iterator=stream())

    with pytest.raises(ValueError):
        asyncio.run(probe.reply(Manager(), "fixture"))


def test_cross_process_mode_uses_owner_handoff_and_retains_existing_cleanup(fixture, monkeypatch):
    def launch(root, sockets, body, output, check, proof):
        assert fixture["managers"][0].closed
        request = output / "owner-request.json"
        probe.atomic_json(
            output,
            request.name,
            {
                "data_root": str(root),
                "socket_root": str(sockets),
                "load": body.model_dump(mode="json"),
            },
        )
        probe.owner(request)  # Simulated native manager, not actual process recovery evidence.
        child = fixture["managers"][-1]
        assert child.closed and not child.stopped
        proof["owner_process_exit_confirmed"] = True  # Protocol simulation only.
        return probe.read_json(output / "owner-result.json")

    monkeypatch.setattr(probe, "owner_process", launch)
    result = fixture["run"](cross_process=True)
    assert result["cross_process_restart_tested"] and result["owner_process_exit_confirmed"]
    assert result["native_inference_passed"] and result["owned_stop_confirmed"]
    assert result["first_reply"] == result["retained_reply"]
    assert not result["macos_installer_qualified"]


def test_cross_process_failure_still_stops_the_original_instance(fixture, monkeypatch):
    def fail(root, sockets, body, output, check, proof):
        raise TimeoutError("PRIVATE helper failed")

    monkeypatch.setattr(probe, "owner_process", fail)
    with pytest.raises(TimeoutError):
        fixture["run"](cross_process=True)
    result = probe.read_json(fixture["output"] / "proof.json")
    assert result["owned_stop_confirmed"] and not result["cross_process_restart_tested"]
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["ack", "startup", "stream"])
def test_failed_native_owner_closes_and_stops_before_publishing_success(fixture, monkeypatch, failure):
    fixture["failure"] = failure

    def launch(root, sockets, body, output, check, proof):
        request = output / "owner-request.json"
        probe.atomic_json(
            output,
            request.name,
            {
                "data_root": str(root),
                "socket_root": str(sockets),
                "load": body.model_dump(mode="json"),
            },
        )
        probe.owner(request)

    monkeypatch.setattr(probe, "owner_process", launch)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        fixture["run"](cross_process=True)
    assert not (fixture["output"] / "owner-result.json").exists()
    result = probe.read_json(fixture["output"] / "owner-failure.json")
    assert "PRIVATE" not in json.dumps(result)
    assert all(manager.closed and manager.stopped for manager in fixture["managers"])


@pytest.fixture
def owner_fixture(tmp_path, monkeypatch):
    output = tmp_path / "proof"
    output.mkdir(mode=0o700)
    body = SimpleNamespace(instance_id=uuid4(), model_dump=lambda **kw: {"frozen": True})
    state = {"change": None, "events": []}
    result = {
        "instance_id": str(body.instance_id),
        "model_pid": 37,
        "owner_pid": 30001,
        "reply": {"characters": 13, "sha256": "a" * 64},
    }

    class Child:
        pid = 30001
        returncode = 0

        def __init__(self, argv, **kwargs):
            assert argv[:3] == [sys.executable, "-I", "-B"]
            assert Path(argv[3]).name == "macos_inference_owner.py"
            assert argv[4] == "--run-native-inference"
            assert kwargs["env"] == {
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "LANG": "C.UTF-8",
                "AI_STATION_DATA_HOST_PATH": str(tmp_path),
            }
            assert kwargs["umask"] == 0o077 and kwargs["start_new_session"] is True
            assert all(kwargs[key] == subprocess.DEVNULL for key in ("stdout", "stderr", "stdin"))
            if state["change"]:
                state["change"](result)
            probe.atomic_json(output, "owner-result.json", result)

        def poll(self):
            return self.returncode

        def terminate(self):
            state["events"].append("terminate")

        def wait(self, timeout):
            state["events"].append("wait")
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fixed helper", timeout)
            return self.returncode

        def kill(self):
            state["events"].append("kill")
            self.returncode = -9

    monkeypatch.setattr(probe.subprocess, "Popen", Child)
    state.update(output=output, body=body, result=result, child=Child, root=tmp_path)
    return state


@pytest.mark.parametrize("change", [None, "instance", "owner", "same_pid", "model", "reply", "extra"])
def test_private_owner_handoff_requires_exit_and_exact_identity(owner_fixture, change):
    state = owner_fixture
    changes = {
        "instance": lambda r: r.update(instance_id=str(uuid4())),
        "owner": lambda r: r.update(owner_pid=30002),
        "same_pid": lambda r: r.update(model_pid=30001),
        "model": lambda r: r.update(model_pid=True),
        "reply": lambda r: r["reply"].update(sha256="invalid"),
        "extra": lambda r: r.update(stdout="PRIVATE"),
    }
    state["change"] = changes.get(change)
    proof = {}

    def invoke():
        return probe.owner_process(
            state["root"], state["root"], state["body"], state["output"], lambda: None, proof
        )

    if change:
        with pytest.raises(ValueError):
            invoke()
        assert "owner_process_exit_confirmed" not in proof
    else:
        assert invoke() == state["result"] and proof["owner_process_exit_confirmed"]
    assert not state["events"]
    assert (state["output"] / "owner-request.json").stat().st_mode & 0o777 == 0o600


def test_timed_out_helper_signals_only_its_immediate_child_handle(owner_fixture):
    state = owner_fixture
    state["child"].returncode = None

    def timeout():
        raise TimeoutError("fixed deadline")

    with pytest.raises(TimeoutError):
        probe.owner_process(state["root"], state["root"], state["body"], state["output"], timeout, {})
    assert state["events"] == ["terminate", "wait", "kill", "wait"]


def test_actual_isolated_owner_entry_refuses_linux_before_reading_any_fixture(tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux refusal control; native Mac execution is separately opted in")
    entry = Path(probe.__file__).with_name("macos_inference_owner.py")
    folder = tmp_path / "isolated-owner"
    folder.mkdir(mode=0o700)
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(entry), "--run-native-inference", str(folder / "absent")],
        cwd=folder,
        env={"PATH": "/usr/bin:/bin", "HOME": str(folder)},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 1 and not result.stdout and not result.stderr
    assert not list(folder.iterdir())
