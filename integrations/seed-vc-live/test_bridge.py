# SPDX-License-Identifier: GPL-3.0-only
"""Ordinary tests of the independent worker; never load an inference dependency."""

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("seed_voice_bridge", Path(__file__).with_name("bridge.py"))
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


@pytest.fixture
def request_file(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    data = b"private reference bytes"
    fd = bridge.StreamVoice.memory_file("ai-station-live-reference", data)
    value = {
        "runtime_root": str(runtime),
        "reference_fd": fd,
        "reference_sha256": hashlib.sha256(data).hexdigest(),
        "seed": 825031,
        "parent_pid": os.getpid(),
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    yield path, value, data
    os.close(fd)


def test_accepts_only_a_hash_checked_sealed_memory_snapshot(request_file):
    path, value, data = request_file
    observed, snapshot = bridge.read_request(path)
    assert observed == value and snapshot == data
    with pytest.raises(OSError):
        os.write(value["reference_fd"], b"changed")


@pytest.mark.parametrize(
    "change", ["shared", "symlink", "hash", "unknown", "wrong_seed", "mutable", "disk_file"]
)
def test_requests_cannot_substitute_another_identity_or_read_an_ordinary_file(request_file, change):
    path, value, data = request_file
    extra = None
    if change == "shared":
        path.chmod(0o644)
    elif change == "symlink":
        alias = path.with_name("alias.json")
        alias.symlink_to(path)
        path = alias
    elif change == "hash":
        value["reference_sha256"] = "0" * 64
    elif change == "unknown":
        value["command"] = "never execute"
    elif change == "wrong_seed":
        value["seed"] = True
    elif change == "mutable":
        extra = os.memfd_create("ai-station-live-reference", os.MFD_ALLOW_SEALING)
        os.write(extra, data)
        value["reference_fd"] = extra
        assert fcntl.fcntl(extra, getattr(fcntl, "F_GET_SEALS", 1034)) == 0
    else:
        ordinary = path.with_name("unrelated.wav")
        ordinary.write_bytes(data)
        extra = os.open(ordinary, os.O_RDONLY)
        value["reference_fd"] = extra
    if change not in {"shared", "symlink"}:
        path.write_text(json.dumps(value))
    try:
        with pytest.raises((ValueError, OSError)):
            bridge.read_request(path)
    finally:
        if extra is not None:
            os.close(extra)


def test_host_device_calls_and_unrelated_parent_are_refused():
    with pytest.raises(RuntimeError, match="host audio"):
        bridge.NoHostAudio("sounddevice").query_devices()
    with pytest.raises(ValueError, match="live native parent"):
        bridge.bind_parent(os.getppid() + 1000000)
