"""Offline runtime input/cancellation boundaries; no pip, models or GPU in CI."""

import hashlib
import io
import os
import stat
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import speech_environment as environment


def object_file(root, content=b"fixed input"):
    item = {
        "filename": "fixed.bin",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
    folder = root / "models/store"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / item["sha256"]
    path.write_bytes(content)
    path.chmod(0o444)
    return item, path


def test_complete_builtin_recipe_pins_executable_sources_and_weights():
    value = environment.recipe()
    assert value["profile"] == environment.PROFILE
    assert value["python"] == "3.12" and value["glibc_minimum"] == "2.28"
    assert len(value["inputs"]) == 135
    assert len({v["filename"] for v in value["inputs"]}) == len(value["inputs"])
    assert all(len(v["sha256"]) == 64 and v["size_bytes"] > 0 for v in value["inputs"])
    assert all(v["url"].startswith("https://") for v in value["inputs"])
    for item in value["inputs"]:
        assert environment.archive_path(item["filename"]).name == item["filename"]
        if item["kind"] == "sdk":
            assert item["revision"] in item["url"] and len(item["revision"]) == 40
    versions = {v["name"]: v["version"] for v in value["inputs"] if v["kind"] == "wheel"}
    assert versions["torch"] == versions["torchaudio"] == "2.6.0+cu126"
    assert versions["transformers"] == "5.2.0" and versions["pip"] == "26.2.1"
    assert len([v for v in value["inputs"] if v["kind"] == "model"]) == 6


def test_valid_input_is_hashed_without_import_or_mutation(tmp_path):
    item, path = object_file(tmp_path)
    assert environment.verified_object(tmp_path, item, lambda: None) == path
    assert path.stat().st_nlink == 1 and not path.stat().st_mode & 0o222


@pytest.mark.parametrize("change", ["symlink", "parent_link", "hardlink", "writable", "length", "hash"])
def test_input_cannot_escape_or_change_identity(tmp_path, change):
    root = tmp_path / "data"
    root.mkdir()
    item, path = object_file(root)
    if change == "symlink":
        destination = tmp_path / "external"
        path.rename(destination)
        path.symlink_to(destination)
    elif change == "parent_link":
        folder = root / "models"
        folder.rename(tmp_path / "external")
        folder.symlink_to(tmp_path / "external", target_is_directory=True)
    elif change == "hardlink":
        os.link(path, tmp_path / "alias")
    elif change == "writable":
        path.chmod(0o644)
    elif change == "length":
        item["size_bytes"] += 1
    else:
        path.chmod(0o600)
        path.write_bytes(b"other input")
        path.chmod(0o444)
    with pytest.raises((ValueError, OSError)):
        environment.verified_object(root, item, lambda: None)


def test_input_change_during_hash_cannot_be_used(tmp_path):
    item, path = object_file(tmp_path)

    def change():
        path.chmod(0o600)
        path.write_bytes(b"other input")
        path.chmod(0o444)

    with pytest.raises(ValueError):
        environment.verified_object(tmp_path, item, change)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "x/../../escape", "a\\b", ""])
def test_archive_names_stay_inside_owned_directory(name):
    with pytest.raises(ValueError):
        environment.archive_path(name)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_sdk_archive_cannot_create_links_or_special_files(tmp_path, kind):
    source = tmp_path / "sdk.tar"
    with tarfile.open(source, "w") as archive:
        item = tarfile.TarInfo("sdk/alias")
        item.type, item.linkname = kind, "../../external"
        archive.addfile(item)
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(ValueError):
        environment.unpack_tar(source, destination, lambda: None)
    assert not (tmp_path / "external").exists()


@pytest.mark.parametrize("link", [False, True])
def test_segmenter_archive_cannot_escape_or_link(tmp_path, link):
    source = tmp_path / "tokens.zip"
    with zipfile.ZipFile(source, "w") as archive:
        if link:
            item = zipfile.ZipInfo("alias")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "../../external")
        else:
            archive.writestr("../external", "outside")
    with pytest.raises(ValueError):
        environment.unpack_segmenter(source, tmp_path / "out", lambda: None)
    assert not (tmp_path / "external").exists()


def test_regular_archives_keep_their_content_and_check_cancellation(tmp_path):
    sdk, tokens = tmp_path / "sdk.tar", tmp_path / "tokens.zip"
    with tarfile.open(sdk, "w") as archive:
        item = tarfile.TarInfo("sdk/pyproject.toml")
        item.size = 5
        archive.addfile(item, io.BytesIO(b"fixed"))
    with zipfile.ZipFile(tokens, "w") as archive:
        archive.writestr("features.msgpack", b"tokens")
    destination = tmp_path / "source"
    destination.mkdir()
    checks = []
    result = environment.unpack_tar(sdk, destination, lambda: checks.append(True))
    environment.unpack_segmenter(tokens, tmp_path / "tokens", lambda: checks.append(True))
    assert (result / "pyproject.toml").read_bytes() == b"fixed"
    assert (tmp_path / "tokens/features.msgpack").read_bytes() == b"tokens"
    assert len(checks) == 2


def test_ambient_python_pip_and_proxy_settings_cannot_redirect_preparation(monkeypatch, tmp_path):
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "HTTPS_PROXY",
        "LD_PRELOAD",
    ):
        monkeypatch.setenv(name, "untrusted")
    value = environment.offline_environment(tmp_path)
    assert value["PIP_NO_INDEX"] == value["HF_HUB_OFFLINE"] == "1"
    assert not set(value) & {
        "PYTHONPATH",
        "PYTHONHOME",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "HTTPS_PROXY",
        "LD_PRELOAD",
    }


def test_missing_or_canceled_inputs_never_execute_installer(tmp_path, monkeypatch):
    item, _ = object_file(tmp_path)
    monkeypatch.setattr(environment, "recipe", lambda: {"inputs": [item]})
    calls = []
    monkeypatch.setattr(environment, "command", lambda *a, **kw: calls.append(a))

    def stop():
        raise InterruptedError("Owned operation canceled")

    with pytest.raises(InterruptedError):
        environment.prepare(tmp_path, uuid4(), check=stop)
    assert not calls and not list(tmp_path.rglob("ready.json"))
    item["sha256"] = "0" * 64
    with pytest.raises(FileNotFoundError):
        environment.prepare(tmp_path, uuid4())
    assert not calls


def test_failed_installation_retains_partial_operation_without_claiming_readiness(tmp_path, monkeypatch):
    item, _ = object_file(tmp_path)
    monkeypatch.setattr(environment, "recipe", lambda: {"inputs": [item]})

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic installer failure")

    monkeypatch.setattr(environment, "command", fail)
    identity = uuid4()
    with pytest.raises(RuntimeError):
        environment.prepare(tmp_path, identity)
    assert len(list(tmp_path.rglob("preparing.json"))) == 1
    assert not list(tmp_path.rglob("ready.json"))
    with pytest.raises(ValueError, match="Inspect the existing"):
        environment.prepare(tmp_path, identity)


def test_directory_does_not_follow_an_existing_link(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        environment.directory(tmp_path, "alias/new")
    assert not (tmp_path / "new").exists()


def test_installer_subprocess_inherits_owned_group_and_is_canceled(tmp_path):
    from ai_station_runner.processes import ProcessManager, _identity

    root = tmp_path / "data"
    root.mkdir()
    folder = tmp_path / "environment"
    folder.mkdir()
    marker = tmp_path / "child.pid"
    program = """
import sys
from pathlib import Path
from ai_station_runner.speech_environment import command
command([sys.executable, '-c', 'import os,time,sys;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)', sys.argv[2]], folder=Path(sys.argv[1]), check=lambda: None)
"""
    manager = ProcessManager(root, grace_seconds=0.1)
    identity = str(uuid4())
    record = manager.start(
        run_id=identity,
        argv=[sys.executable, "-c", program, str(folder), str(marker)],
        cwd=root,
        executor="test-offline-preparation",
        env={**os.environ, "PYTHONPATH": str(Path(environment.__file__).parent.parent)},
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        child = int(marker.read_text())
        assert os.getpgid(child) == record["process_group_id"]
        manager.cancel(identity)
        deadline = time.monotonic() + 3
        while (
            (observation := _identity(child)) and observation["state"] != "Z" and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert observation is None or observation["state"] == "Z"
    finally:
        manager.shutdown()


def test_speech_cli_requires_actual_scope_before_importing_models(tmp_path, monkeypatch):
    import json

    from ai_station_runner import managed_speech_job

    (tmp_path / "ready.json").write_text(
        json.dumps({"environment_prepared": True, "profile": environment.PROFILE})
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "speech",
            "--run-id",
            str(uuid4()),
            "--environment",
            str(tmp_path),
            "--ref",
            str(tmp_path / "ref.wav"),
            "--text",
            "Test",
            "--out",
            str(tmp_path / "result.wav"),
        ],
    )
    with pytest.raises(ValueError, match="outside its owned memory scope"):
        managed_speech_job.main()
    assert not (tmp_path / "result.wav").exists()
