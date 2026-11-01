"""Real disposable Linux process/UDS controls with simulated Mac facts, not Mac qualification."""

import asyncio
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import darwin_llama as native
from ai_station_runner.local_model import Completion
from ai_station_runner.processes import ProcessManager
from pydantic import ValidationError

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux controls do not qualify native Mac execution"
)
NATIVE_COMMAND = native.command

SERVER = """
import json,os,socketserver,sys
from http.server import BaseHTTPRequestHandler
path,alias,context,mode=sys.argv[1:];context=int(context)
assert 'NATIVE_TEST_SECRET' not in os.environ
print('PRIVATE-OTHER-USER',flush=True)
print('PRIVATE-OTHER-USER',file=sys.stderr,flush=True)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):print('PRIVATE-OTHER-USER',file=sys.stderr,flush=True)
 def reply(self,value,status=200,kind='application/json'):
  data=value.encode() if isinstance(value,str) else json.dumps(value).encode()
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/health':return self.reply({},503 if mode=='slow' else 200)
  if self.path=='/v1/models':return self.reply({'data':[{'id':'wrong' if mode=='wrong_alias' else alias}]})
  if self.path=='/props':
   if mode=='oversized':return self.reply('X'*70000)
   if mode=='malformed':return self.reply([])
   return self.reply({'default_generation_settings':{'n_ctx':512 if mode=='wrong_context' else context}})
  self.reply({},404)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  assert body['model']==alias
  self.reply('data: '+json.dumps({'choices':[{'delta':{'content':'FAKE_NATIVE_OK'}}]})+'\\n\\ndata: [DONE]\\n\\n',kind='text/event-stream')
os.umask(0o077)
with socketserver.UnixStreamServer(path,Handler) as server:
 os.chmod(path,0o600)
 server.serve_forever()
"""


@pytest.fixture
def rig(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    socket_root = Path(tempfile.mkdtemp(prefix="aist-native-"))
    fields = {
        "general.architecture": "qwen3",
        "qwen3.block_count": 2,
        "qwen3.context_length": 131072,
        "qwen3.embedding_length": 256,
        "qwen3.attention.head_count": 2,
        "qwen3.attention.head_count_kv": 1,
    }
    data = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 0, len(fields)))
    for key, value in fields.items():
        encoded = key.encode()
        data += struct.pack("<Q", len(encoded)) + encoded
        if isinstance(value, str):
            encoded = value.encode()
            data += struct.pack("<IQ", 8, len(encoded)) + encoded
        else:
            data += struct.pack("<II", 4, value)
    digest = hashlib.sha256(data).hexdigest()
    model = root / "models/store" / digest
    model.parent.mkdir(parents=True)
    model.write_bytes(data)
    model.chmod(0o444)
    context = native.inspect_context(model, len(data), model.stat().st_mtime)
    body = native.NativeLoad(
        instance_id=uuid4(),
        run_id=uuid4(),
        bundle_operation_id=uuid4(),
        bundle_manifest_sha256="a" * 64,
        architecture="arm64",
        compute="cpu",
        model_path="models/store/" + digest,
        model_sha256=digest,
        size_bytes=len(data),
        mtime=model.stat().st_mtime,
        ram_mib=native.memory_budget(len(data), 4096, context),
        startup_deadline_at=datetime.now(timezone.utc) + timedelta(seconds=20),
        permissions=["manage_models", "filesystem_read"],
    )
    script = tmp_path / "fake_server.py"
    script.write_text(SERVER)
    state = {
        "root": root,
        "socket_root": socket_root,
        "body": body,
        "mode": "normal",
        "context": context,
        "managers": [],
    }
    state["hardware"] = {
        "memory": {"available_mib": 65536},
        "metal": {
            "complete": True,
            "devices": [
                {
                    "registry_id": "0000000000000123",
                    "unified_memory": True,
                    "recommended_working_set_bytes": 64 * 1024**3,
                }
            ],
        },
    }
    monkeypatch.setattr(
        native,
        "platform",
        SimpleNamespace(
            system=lambda: "Darwin", machine=lambda: "arm64", mac_ver=lambda: ("14.0", None, None)
        ),
    )
    monkeypatch.setattr(
        native.bundle, "inspect", lambda *a: {"manifest_sha256": "a" * 64, "relative_path": "prepared"}
    )
    monkeypatch.setattr(native.bundle, "recipe", lambda *a: {"compiled_backends": ["cpu", "metal"]})
    monkeypatch.setattr(native, "collect", lambda *a: state["hardware"])
    monkeypatch.setattr(
        native,
        "command",
        lambda engine, model, socket, body: [
            sys.executable,
            "-I",
            "-S",
            str(script),
            str(socket),
            str(body.instance_id),
            str(body.context_size),
            state["mode"],
        ],
    )

    def manager():
        item = native.NativeLlamaManager(
            root, socket_root, processes=ProcessManager(root, grace_seconds=0.05)
        )
        state["managers"].append(item)
        return item

    state["manager"] = manager
    state["owner"] = manager()
    try:
        yield state
    finally:
        for item in state["managers"]:
            item.close()
        for item in state["managers"]:
            item.processes.shutdown()
        deadline = time.monotonic() + 3
        while any(item.processes._live for item in state["managers"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        shutil.rmtree(socket_root)


def wait(manager, identity, status):
    deadline = time.monotonic() + 4
    result = None
    while time.monotonic() < deadline:
        result = manager.inspect(identity)
        if result["status"] == status:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Native fixture did not reach {status}: {result}")


def test_owned_load_readiness_completion_stop_and_private_logs(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    monkeypatch.setenv("NATIVE_TEST_SECRET", "PRIVATE-TEST-TOKEN")
    owner.load(body)
    ready = wait(owner, body.instance_id, "ready")
    assert ready["n_ctx"] == 4096 and ready["inference_qualified"] is False
    assert ready["memory_enforcement"] == "admission_only" and not ready["zero_swap_guaranteed"]
    again = owner.load(body)
    assert again["pid"] == ready["pid"]

    class Incoming:
        async def is_disconnected(self):
            return False

    async def completion():
        request = Completion(
            model=str(body.instance_id),
            messages=[{"role": "user", "content": "private user input"}],
            temperature=0,
            max_tokens=64,
            stream=True,
        )
        result = await owner.completion(body.instance_id, request, Incoming())
        return b"".join(
            [part if isinstance(part, bytes) else part.encode() async for part in result.body_iterator]
        )

    stream = asyncio.run(completion())
    assert b"FAKE_NATIVE_OK" in stream and b"\n\ndata: [DONE]\n\n" in stream
    process = owner.processes.inspect(str(body.run_id))
    assert process["logs_suppressed"] is True and process["stdout"] == process["stderr_tail"] == ""
    assert not any(
        key in json.dumps(ready)
        for key in ["stdout", "stderr", str(body.bundle_operation_id), "models/store"]
    )
    owner.stop(body.instance_id, ["manage_models"])
    assert wait(owner, body.instance_id, "stopped")["alive"] is False
    assert owner.load(body)["status"] == "stopped"


def test_owner_replacement_adopts_same_live_process_without_reexecution(rig):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    pid = wait(owner, body.instance_id, "ready")["pid"]
    owner.close()
    replacement = rig["manager"]()
    assert replacement.load(body)["pid"] == pid
    assert len(replacement.processes._load()) == 1
    replacement.stop(body.instance_id, ["manage_models"])
    assert wait(replacement, body.instance_id, "stopped")["alive"] is False


def test_lost_dispatch_acknowledgement_never_starts_a_second_process(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    start = owner.processes.start
    count = []

    def lost(**kwargs):
        result = start(**kwargs)
        count.append(result["pid"])
        raise OSError("lost private acknowledgement")

    monkeypatch.setattr(owner.processes, "start", lost)
    with pytest.raises(OSError):
        owner.load(body)
    owner.close()
    replacement = rig["manager"]()
    result = wait(replacement, body.instance_id, "ready")
    assert replacement.load(body)["pid"] == result["pid"] == count[0] and len(count) == 1


def test_stop_before_load_wins_without_starting_payload(rig):
    owner, body = rig["owner"], rig["body"]
    assert owner.stop(body.instance_id, ["manage_models"])["status"] == "stopped"
    assert owner.load(body)["status"] == "stopped"
    assert owner.processes._load() == {}


@pytest.mark.parametrize("mode", ["slow", "wrong_alias", "wrong_context", "oversized", "malformed"])
def test_startup_deadline_and_mismatched_readiness_stop_only_owned_group(rig, mode):
    rig["mode"] = mode
    owner = rig["owner"]
    body = rig["body"].model_copy(
        update={"startup_deadline_at": datetime.now(timezone.utc) + timedelta(seconds=0.5)}
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
    try:
        owner.load(body)
        failed = wait(owner, body.instance_id, "failed")
        assert not failed["alive"] and "Native" in failed["error"]
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3)


@pytest.mark.parametrize("change", ["ram", "engine", "architecture", "permissions", "mtime"])
def test_invalid_authority_or_frozen_inputs_cannot_launch_a_process(rig, change):
    body = rig["body"]
    updates = {
        "ram": {"ram_mib": body.ram_mib - 1},
        "engine": {"bundle_manifest_sha256": "b" * 64},
        "architecture": {"architecture": "x86_64"},
        "permissions": {"permissions": []},
        "mtime": {"mtime": body.mtime + 1},
    }[change]
    with pytest.raises((ValueError, native.HTTPException)):
        rig["owner"].load(body.model_copy(update=updates))
    assert rig["owner"].processes._load() == {}


def test_metal_requires_matching_unique_unified_identity_and_advisory_budget(rig):
    body = rig["body"].model_copy(update={"compute": "metal", "metal_registry_id": "0000000000000123"})
    owner = rig["owner"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    other = body.model_copy(update={"instance_id": uuid4(), "run_id": uuid4()})
    with pytest.raises(ValueError, match="reserved"):
        owner.load(other)


@pytest.mark.parametrize("change", ["unknown", "identity", "nonunified", "count", "budget"])
def test_uncertain_metal_facts_never_fall_back_to_cpu(rig, change):
    body = rig["body"].model_copy(update={"compute": "metal", "metal_registry_id": "0000000000000123"})
    report = rig["hardware"]["metal"]
    device = report["devices"][0]
    if change == "unknown":
        report["complete"] = False
    if change == "identity":
        device["registry_id"] = "0000000000000456"
    if change == "nonunified":
        device["unified_memory"] = False
    if change == "count":
        report["devices"].append(dict(device))
    if change == "budget":
        device["recommended_working_set_bytes"] = 1
    with pytest.raises(ValueError):
        rig["owner"].load(body)
    assert rig["owner"].processes._load() == {}


def test_native_ram_reservations_remain_held_for_existing_live_models(rig):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    rig["hardware"]["memory"]["available_mib"] = body.ram_mib * 2 - 1
    with pytest.raises(ValueError, match="reservations"):
        owner.load(body.model_copy(update={"instance_id": uuid4(), "run_id": uuid4()}))


def test_changed_request_and_unowned_dispatch_require_inspection(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    with pytest.raises(ValueError, match="immutable"):
        owner.load(body.model_copy(update={"run_id": uuid4()}))
    from ai_station_runner.processes import ProcessNotOwned

    with monkeypatch.context() as context:
        context.setattr(
            owner.processes, "inspect", lambda *a, **k: (_ for _ in ()).throw(ProcessNotOwned("missing"))
        )
        assert owner.load(body)["status"] == "inspection_required"
    assert len(owner.processes._load()) == 1


def test_native_budget_supports_large_inspected_models_and_100k_context():
    profile = {"source": "gguf_header", "q8_kv_bytes_per_token": 256, "trained_context": 131072}
    budget = native.memory_budget(17 * 1024**3, 100352, profile)
    assert budget > 17 * 1024 and budget < 24 * 1024
    for value in [True, 0, -1, 1.5]:
        with pytest.raises(ValueError):
            native.memory_budget(value, 4096, profile)


def test_typed_request_rejects_arbitrary_paths_modes_commands_and_naive_deadlines(rig):
    data = rig["body"].model_dump()
    for changes in [
        {"model_path": "/etc/passwd"},
        {"command": "sh"},
        {"architecture": "linux"},
        {"startup_deadline_at": datetime.now()},
        {"context_size": True},
        {"compute": "metal", "metal_registry_id": None},
    ]:
        with pytest.raises(ValidationError):
            native.NativeLoad.model_validate(data | changes)


def test_unsupported_host_fails_before_native_storage_or_process_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        native,
        "platform",
        SimpleNamespace(system=lambda: "Linux", machine=lambda: "x86_64", mac_ver=lambda: ("", None, None)),
    )
    with pytest.raises(RuntimeError):
        native.NativeLlamaManager(tmp_path, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_persisted_stop_is_delivered_after_owner_replacement(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    pid = wait(owner, body.instance_id, "ready")["pid"]
    owner.close()

    def unavailable(*args):
        raise OSError("Owner lost signal delivery")

    with monkeypatch.context() as context:
        context.setattr(owner.processes, "cancel", unavailable)
        with pytest.raises(OSError):
            owner.stop(body.instance_id, ["manage_models"])
    assert owner._read(str(body.instance_id))["desired"] == "stopped"
    assert owner.processes.inspect(str(body.run_id))["alive"]
    replacement = rig["manager"]()
    # Do not poll inspect here: the replacement watchdog must deliver the Stop.
    deadline = time.monotonic() + 4
    while replacement.processes.inspect(str(body.run_id))["alive"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert replacement.inspect(body.instance_id)["status"] == "stopped"
    assert replacement.processes.inspect(str(body.run_id))["pid"] == pid
    assert replacement.load(body)["status"] == "stopped"


def test_replacement_owner_keeps_the_original_startup_deadline(rig):
    rig["mode"] = "slow"
    owner = rig["owner"]
    body = rig["body"].model_copy(
        update={"startup_deadline_at": datetime.now(timezone.utc) + timedelta(seconds=0.6)}
    )
    owner.load(body)
    owner.close()
    replacement = rig["manager"]()
    result = wait(replacement, body.instance_id, "failed")
    assert not result["alive"] and result["error"] == "Native startup deadline exceeded"
    assert len(replacement.processes._load()) == 1


def test_stop_watchdog_retries_transient_signal_failure_without_an_inspection_poll(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    original = owner.processes.cancel
    attempts = []

    def transient(*args):
        attempts.append(args)
        if len(attempts) <= 2:
            raise OSError("Transient delivery failure")
        return original(*args)

    monkeypatch.setattr(owner.processes, "cancel", transient)
    with pytest.raises(OSError):
        owner.stop(body.instance_id, ["manage_models"])
    deadline = time.monotonic() + 4
    while owner.processes.inspect(str(body.run_id))["alive"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(attempts) >= 3
    assert owner.inspect(body.instance_id)["status"] == "stopped"


def test_unknown_dispatch_is_never_reexecuted_or_assumed_gone(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]

    def unavailable(**kwargs):
        raise OSError("No durable launch acknowledgement")

    monkeypatch.setattr(owner.processes, "start", unavailable)
    with pytest.raises(OSError):
        owner.load(body)
    assert owner.load(body)["status"] == "inspection_required"
    other = body.model_copy(update={"instance_id": uuid4(), "run_id": uuid4()})
    with pytest.raises(ValueError, match="requires inspection"):
        owner.load(other)
    assert owner.processes._load() == {}


@pytest.mark.parametrize(
    "field,value", [("request_hash", "b" * 64), ("dispatch_started", "true"), ("ready_at", float("nan"))]
)
def test_changed_journal_cannot_authorize_replay_or_signal(rig, monkeypatch, field, value):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    owner.close()
    saved = owner._read(str(body.instance_id))
    owner._save(str(body.instance_id), saved | {field: value})
    signals = []
    with monkeypatch.context() as context:
        context.setattr(owner.processes, "cancel", lambda *a: signals.append(a))
        with pytest.raises(ValueError, match="identity"):
            owner.load(body)
        with pytest.raises(ValueError, match="identity"):
            owner.stop(body.instance_id, ["manage_models"])
    assert not signals and owner.processes.inspect(str(body.run_id))["alive"]


def test_altered_process_ownership_never_authorizes_a_signal(rig, monkeypatch):
    owner, body = rig["owner"], rig["body"]
    owner.load(body)
    wait(owner, body.instance_id, "ready")
    inspect = owner.processes.inspect
    signals = []
    with monkeypatch.context() as context:
        context.setattr(owner.processes, "inspect", lambda *a: inspect(*a) | {"executor": "unrelated"})
        context.setattr(owner.processes, "cancel", lambda *a: signals.append(a))
        with pytest.raises(ValueError, match="ownership"):
            owner.stop(body.instance_id, ["manage_models"])
    assert not signals
    assert inspect(str(body.run_id))["alive"]


@pytest.mark.parametrize("change", ["long", "symlink", "public"])
def test_unknown_or_unsafe_socket_storage_cannot_launch(rig, change):
    owner, body = rig["owner"], rig["body"]
    if change == "long":
        owner.socket_root = rig["socket_root"] / ("x" * 75)
        owner.socket_root.mkdir(mode=0o700)
    elif change == "public":
        rig["socket_root"].chmod(0o755)
    else:
        (rig["socket_root"] / str(body.instance_id)).symlink_to(rig["root"], target_is_directory=True)
    with pytest.raises((ValueError, FileExistsError)):
        owner.load(body)
    assert owner.processes._load() == {}


@pytest.mark.parametrize("compute", ["cpu", "metal"])
def test_fixed_native_command_uses_reviewed_device_and_no_network_model_download(rig, compute):
    body = rig["body"].model_copy(update={"compute": compute})
    argv = NATIVE_COMMAND(Path("/engine"), Path("/model"), Path("/private/model.sock"), body)
    assert argv[0] == "/engine/llama-server"
    assert argv[argv.index("--host") + 1] == "/private/model.sock"
    assert argv[argv.index("--device") + 1] == ("none" if compute == "cpu" else "MTL0")
    assert argv[argv.index("--gpu-layers") + 1] == ("0" if compute == "cpu" else "all")
    assert ("--no-kv-offload" in argv) == (compute == "cpu")
    assert "--offline" in argv and "--no-webui" in argv
    assert argv[argv.index("--fit") + 1] == "off"


def test_stop_requires_authority_and_completion_cannot_select_another_model(rig):
    owner, body = rig["owner"], rig["body"]
    with pytest.raises(native.HTTPException) as error:
        owner.stop(body.instance_id, [])
    assert error.value.status_code == 403
    assert owner._read(str(body.instance_id)) is None
    request = Completion(
        model=str(uuid4()),
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=64,
        stream=True,
    )
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(owner.completion(body.instance_id, request, None))
