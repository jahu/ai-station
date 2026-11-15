import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from ai_station_runner import live_environment
from ai_station_runner.live_broker import LiveBroker
from ai_station_runner.live_contract import LiveRequest, Reference, reference_snapshot
from ai_station_runner.live_ipc import PREFIX, read_async, read_sync, snapshot_bytes, write_async, write_sync
from ai_station_runner.live_protocol import AUDIO_BYTES, Kind, Packet, encode
from ai_station_runner.unix_sockets import unix_address
from pydantic import ValidationError


def request(**overrides):
    return {
        "run_id": "6f5e0241-4b75-4356-9186-a394ae9ff032",
        "managed_runtime": {
            "profile": live_environment.PROFILE,
            "manifest_sha256": live_environment.MANIFEST,
            "environment_id": "b" * 64,
        },
        "image": {"relative_path": "artifacts/face.png", "sha256": "a" * 64, "size_bytes": 3},
        "gpus": [3],
        "seed": 42,
        "deadline_at": time.time() + 60,
        "permissions": ["filesystem_read", "workspace_write"],
        **overrides,
    }


def test_live_recipe_freezes_every_source_and_separate_license():
    recipe = live_environment.recipe()
    assert len(recipe["inputs"]) == 118
    assert live_environment.fingerprint(recipe) == live_environment.MANIFEST
    assert len({v["filename"] for v in recipe["inputs"]}) == 118
    assert len({v["sha256"] for v in recipe["inputs"]}) == 118
    assert "noncommercial research only" in recipe["license_notice"]
    for item in recipe["inputs"]:
        assert item["url"].startswith("https://")


@pytest.mark.parametrize(
    "changes",
    [
        {"image": None},
        {"gpus": []},
        {"gpus": [True]},
        {"gpus": [-1]},
        {"gpus": [3, 3]},
        {"gpus": [3, 4]},
        {"permissions": []},
        {"seed": True},
        {"ram_mib": 1024},
        {"command": "echo unsafe"},
    ],
)
def test_closed_live_request_rejects_unreserved_or_untyped_inputs(changes):
    with pytest.raises(ValidationError):
        LiveRequest.model_validate(request(**changes))


def test_duplex_session_needs_two_distinct_gpus():
    voice = request()["image"]
    with pytest.raises(ValidationError):
        LiveRequest.model_validate(request(voice=voice))
    body = LiveRequest.model_validate(request(voice=voice, gpus=[3, 7]))
    assert body.gpus == [3, 7]


def test_reference_snapshot_is_sealed_and_survives_source_removal(tmp_path):
    path = tmp_path / "artifacts/face.png"
    path.parent.mkdir()
    path.write_bytes(b"private-reference")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ref = Reference(relative_path="artifacts/face.png", size_bytes=path.stat().st_size, sha256=digest)
    fd = reference_snapshot(tmp_path, ref)
    try:
        path.unlink()
        assert snapshot_bytes(fd, digest) == b"private-reference"
        with pytest.raises(OSError):
            os.write(fd, b"changed")
        with pytest.raises(ValueError):
            snapshot_bytes(fd, "0" * 64)
    finally:
        os.close(fd)
    assert not list(tmp_path.rglob("*.wav"))


@pytest.mark.parametrize("mode", ["symlink", "hardlink", "hash", "outside"])
def test_reference_snapshot_refuses_changed_or_escaping_files(tmp_path, mode):
    folder = tmp_path / "artifacts"
    folder.mkdir()
    path = folder / "source.png"
    path.write_bytes(b"abc")
    if mode == "symlink":
        (folder / "link.png").symlink_to(path)
        relative = "artifacts/link.png"
    elif mode == "hardlink":
        os.link(path, folder / "link.png")
        relative = "artifacts/source.png"
    else:
        relative = "artifacts/source.png" if mode == "hash" else "../source.png"
    ref = Reference(relative_path=relative, size_bytes=3, sha256="0" * 64)
    with pytest.raises((ValueError, OSError)):
        reference_snapshot(tmp_path, ref)


def test_local_ipc_checks_lengths_and_truncation():
    output = io.BytesIO()
    write_sync(output, b"hello")
    assert read_sync(io.BytesIO(output.getvalue())) == b"hello"
    assert read_sync(io.BytesIO()) is None
    with pytest.raises(EOFError):
        read_sync(io.BytesIO(PREFIX.pack(4) + b"a"))
    with pytest.raises(ValueError):
        read_sync(io.BytesIO(PREFIX.pack(10_000_000)))


@pytest.mark.asyncio
async def test_broker_refuses_intruder_without_ending_owned_session(tmp_path):
    broker = LiveBroker(secret="secret", deadline_at=time.time() + 60)
    path = tmp_path / "stream.sock"
    task = asyncio.create_task(broker.serve(path, connect_timeout=3))
    while not path.exists():
        await asyncio.sleep(0.001)
    with unix_address(path) as address:
        reader, writer = await asyncio.open_unix_connection(address)
    await write_async(writer, b"wrong-secret")
    assert await reader.read() == b""
    writer.close()
    await writer.wait_closed()
    assert not broker.finished.is_set()
    with unix_address(path) as address:
        reader, writer = await asyncio.open_unix_connection(address)
    await write_async(writer, b"secret")
    assert json.loads(await read_async(reader)) == {"ready": True}
    writer.close()
    await writer.wait_closed()
    await asyncio.wait_for(task, 1)
    assert broker.finished.is_set() and broker.used and not path.exists()


@pytest.mark.asyncio
async def test_broker_rejects_audio_without_enabled_engine(tmp_path):
    broker = LiveBroker(secret="secret", deadline_at=time.time() + 60)
    path = tmp_path / "stream.sock"
    task = asyncio.create_task(broker.serve(path, connect_timeout=3))
    while not path.exists():
        await asyncio.sleep(0.001)
    reader, writer = await asyncio.open_unix_connection(str(path))
    await write_async(writer, b"secret")
    await read_async(reader)
    await write_async(writer, encode(Packet(Kind.MICROPHONE, 0, 0, bytes(AUDIO_BYTES))))
    assert json.loads(await read_async(reader))["error"] == "invalid_media_packet"
    assert await reader.read() == b""
    writer.close()
    await writer.wait_closed()
    await asyncio.wait_for(task, 1)
    assert broker.error is not None


def test_inference_child_dies_with_owned_parent(tmp_path):
    program = """
import os, subprocess, sys, time
code = 'import os,time; from ai_station_runner.live_ipc import bind_parent; bind_parent(int(__import__("sys").argv[1])); print("bound",flush=True); time.sleep(60)'
p = subprocess.Popen([sys.executable,'-c',code,str(os.getpid())], stdout=subprocess.PIPE, text=True)
assert p.stdout.readline().strip() == 'bound'
print(p.pid,flush=True)
time.sleep(60)
"""
    with subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True) as parent:
        child = int(parent.stdout.readline())
        parent.kill()
        parent.wait(timeout=3)
        until = time.monotonic() + 3
        while time.monotonic() < until:
            status = Path(f"/proc/{child}/stat")
            if not status.exists() or status.read_text().split(") ", 1)[1][0] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("The owned inference child survived loss of its parent")
