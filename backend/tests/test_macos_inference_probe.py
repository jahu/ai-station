"""Probe protocol controls; native facts/SDK/inference are simulated, not Mac evidence."""

import asyncio
import hashlib
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

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
