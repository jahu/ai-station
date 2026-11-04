"""Managed speech never overrides external configuration or follows data escapes."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import audio, speech_environment, speech_prepare
from ai_station_runner.speech_selection import selection


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_prepare, "QUALIFIED", True)
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    item = {"kind": "model", "filename": "ve.pt", "sha256": "a" * 64, "size_bytes": 5}
    recipe = {"profile": speech_environment.PROFILE, "inputs": [item]}
    monkeypatch.setattr(speech_environment, "recipe", lambda: recipe)
    digest = speech_environment.fingerprint(recipe)
    identity = str(uuid4())
    folder = tmp_path / "runtime/speech" / digest / identity
    for name in ("venv/bin", "python/bin", "cache", "models"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    binary = folder / "python/bin/python3.12"
    binary.write_bytes(b"fixed")
    binary.chmod(0o700)
    (folder / "venv/bin/python").symlink_to("../../python/bin/python3.12")
    weight = store / item["sha256"]
    weight.write_bytes(b"fixed")
    weight.chmod(0o444)
    (folder / "models/ve.pt").symlink_to(weight)
    active = {"profile": speech_environment.PROFILE, "operation_id": identity, "manifest_sha256": digest}
    pointer = tmp_path / "runtime/speech/active.json"
    pointer.write_text(json.dumps(active))
    pointer.chmod(0o600)
    receipt = {
        **active,
        "relative_path": folder.relative_to(tmp_path).as_posix(),
        "environment_prepared": True,
    }
    (folder / "ready.json").write_text(json.dumps(receipt))
    (folder / "ready.json").chmod(0o600)
    settings = SimpleNamespace(
        chatterbox_python="", chatterbox_script="", chatterbox_cache="", host_data_dir=lambda: tmp_path
    )
    return settings, folder, pointer, weight


def test_exact_owned_environment_is_selected_only_after_activation(prepared):
    settings, folder, _, _ = prepared
    result = selection(settings)
    assert result["managed"] and result["environment"] == folder
    assert result["python"] == folder / "venv/bin/python"
    assert result["python"].resolve().is_relative_to(folder / "python")


def test_existing_external_configuration_keeps_its_settings(prepared):
    settings, _, _, _ = prepared
    settings.chatterbox_python = "/configured/python"
    settings.chatterbox_script = "/configured/speech.py"
    settings.chatterbox_cache = "/configured/cache"
    result = selection(settings)
    assert not result["managed"] and result["environment"] is None
    assert str(result["script"]) == "/configured/speech.py"


def test_partial_external_configuration_never_silently_falls_back(prepared):
    settings, _, _, _ = prepared
    settings.chatterbox_script = "/configured/missing.py"
    result = selection(settings)
    assert not result["managed"] and result["python"] is None


@pytest.mark.parametrize(
    "change",
    [
        "pointer_link",
        "ready_link",
        "wrong_manifest",
        "binary_escape",
        "model_escape",
        "writable_model",
        "incomplete",
    ],
)
def test_modified_or_escaped_environment_is_not_selected(prepared, tmp_path, change):
    settings, folder, pointer, weight = prepared
    if change == "pointer_link":
        saved = tmp_path / "pointer.json"
        pointer.rename(saved)
        pointer.symlink_to(saved)
    elif change == "ready_link":
        path = folder / "ready.json"
        saved = tmp_path / "ready.json"
        path.rename(saved)
        path.symlink_to(saved)
    elif change == "wrong_manifest":
        value = json.loads(pointer.read_text())
        value["manifest_sha256"] = "b" * 64
        pointer.write_text(json.dumps(value))
    elif change == "binary_escape":
        alias = folder / "venv/bin/python"
        alias.unlink()
        alias.symlink_to("/usr/bin/python3")
    elif change == "model_escape":
        alias = folder / "models/ve.pt"
        alias.unlink()
        alias.symlink_to(tmp_path / "private-user-file")
    elif change == "writable_model":
        weight.chmod(0o600)
    else:
        (folder / "ready.json").unlink()
    assert selection(settings) is None


def test_managed_audio_uses_fixed_scope_and_owned_runtime_with_full_text(prepared, monkeypatch):
    import wave

    settings, folder, _, _ = prepared
    root = settings.host_data_dir()
    reference = root / "artifacts/reference.wav"
    reference.parent.mkdir()
    with wave.open(str(reference), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 3200)
    monkeypatch.setattr(audio, "get_settings", lambda: settings)
    monkeypatch.setattr(audio, "collect", lambda _: {"gpus": [{"index": 7}]})
    from ai_station_runner import memory_scope

    monkeypatch.setattr(memory_scope, "scope_prefix", lambda identity, maximum: ["fixed-scope", str(maximum)])
    captured = {}

    class Manager:
        def start(self, **kwargs):
            captured.update(kwargs)
            return kwargs

    text = "Zachowaj całą wypowiedź bez pomijania żadnej części. " * 8
    body = audio.AudioRequest(
        run_id=uuid4(),
        text=text,
        reference_relative="artifacts/reference.wav",
        gpu=7,
        permissions=["filesystem_read", "workspace_write"],
    )
    audio.start_audio(Manager(), body)
    assert captured["argv"][:2] == ["fixed-scope", "11264"]
    assert captured["argv"][2] == str(folder / "venv/bin/python")
    assert Path(captured["argv"][3]).name == "managed_speech_job.py"
    assert captured["argv"][captured["argv"].index("--text") + 1] == text.strip()
    assert captured["argv"][captured["argv"].index("--environment") + 1] == str(folder)
    assert captured["argv"][captured["argv"].index("--run-id") + 1] == str(body.run_id)
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "7"
    assert captured["env"]["HF_HUB_OFFLINE"] == "1"
    assert not list((root / "runs").glob("*/speech/request.json"))
