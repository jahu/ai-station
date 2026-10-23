import hashlib
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import music, music_entry, music_protocol
from ai_station_runner.processes import ProcessNotOwned
from pydantic import ValidationError


def request(**kwargs):
    return music.MusicRequest(
        **{
            "run_id": uuid4(),
            "caption": "Calm piano",
            "duration_seconds": 10,
            "seed": 42,
            "gpu": 7,
            "permissions": sorted(music.PERMISSIONS),
            **kwargs,
        }
    )


def pcm(path, seconds=10, *, audible=True, truncated=False):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        for _ in range(seconds):
            audio.writeframesraw((b"\x01\x00" if audible else b"\0\0") * 96000)
    if truncated:
        with path.open("r+b") as handle:
            handle.truncate(path.stat().st_size - 3)


def test_long_music_pcm_does_not_use_voice_reference_limit(tmp_path):
    path = tmp_path / "music.wav"
    pcm(path, 130)
    assert path.stat().st_size > 20 * 1024 * 1024
    assert music_protocol.wav_metadata(path, requested_seconds=130) == {
        "duration_seconds": 130,
        "sample_rate": 48000,
        "channels": 2,
    }


@pytest.mark.parametrize("kind", ["silent", "truncated", "short", "clamped"])
def test_invalid_music_cannot_be_published_as_success(tmp_path, kind):
    path = tmp_path / "music.wav"
    pcm(path, seconds=9 if kind == "short" else 10, audible=kind != "silent", truncated=kind == "truncated")
    with pytest.raises(ValueError):
        music_protocol.wav_metadata(path, requested_seconds=30 if kind == "clamped" else 10)


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_seconds": 9},
        {"duration_seconds": 601},
        {"duration_seconds": True},
        {"seed": -1},
        {"gpu": "7"},
        {"caption": " "},
        {"caption": "x" * 513},
        {"instrumental": True, "lyrics": "some lyrics"},
        {"instrumental": False},
        {"lyrics": "x" * 4097},
        {"command": "curl anything"},
        {"output_path": "/tmp/escape.wav"},
    ],
)
def test_request_rejects_unbounded_parameters_or_arbitrary_commands(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.fixture
def models(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    files = []
    for name, data in [("vae/model.bin", b"weights"), ("acestep-v15-turbo/model.py", b"approved")]:
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"files": files}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(music_protocol, "MANIFEST_SHA256", digest)
    (root / "ai-station-model.json").write_text(json.dumps(manifest))
    return root


def test_worker_hashes_weights_and_preflight_hashes_executable_code(models):
    music_protocol.model_manifest(models, verify_weights=True)
    (models / "vae/model.bin").write_bytes(b"changed")
    music_protocol.model_manifest(models)
    with pytest.raises(ValueError, match="SHA-256"):
        music_protocol.model_manifest(models, verify_weights=True)
    (models / "acestep-v15-turbo/model.py").write_bytes(b"modified")
    with pytest.raises(ValueError, match="SHA-256"):
        music_protocol.model_manifest(models)


def test_checkpoint_view_does_not_overwrite_the_approved_model(models, tmp_path, monkeypatch):
    source = tmp_path / "source/acestep"
    (source / "models/turbo").mkdir(parents=True)
    (source / "models/turbo/model.py").write_text("pinned package code")
    monkeypatch.setattr(music_protocol, "verify_source", lambda path: source)
    destination = tmp_path / "private-checkpoints"
    music_protocol.checkpoint_view(models, source.parent, destination)
    assert (models / "acestep-v15-turbo/model.py").read_text() == "approved"
    assert (destination / "acestep-v15-turbo/model.py").read_text() == "pinned package code"
    assert (destination / "vae/model.bin").resolve() == models / "vae/model.bin"
    with pytest.raises(FileExistsError):
        music_protocol.checkpoint_view(models, source.parent, destination)


@pytest.mark.parametrize("location", ["vae/model.bin", "acestep-v15-turbo/model.py", "ai-station-model.json"])
def test_even_symlinks_inside_model_root_are_rejected(models, location):
    path = models / location
    moved = path.with_name("original-" + path.name)
    path.rename(moved)
    path.symlink_to(moved)
    with pytest.raises(ValueError, match="symlinks"):
        music_protocol.model_manifest(models)


def test_request_launch_has_fixed_argv_no_credentials_and_replays_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SOME_SECRET", "must-not-leak")
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setattr(
        music, "configured", lambda: (tmp_path / "python", tmp_path / "source", tmp_path / "model")
    )
    monkeypatch.setattr(music, "collect", lambda root: {"gpus": [{"index": 7}]})
    records, launches = {}, []

    def inspect(run_id):
        if run_id not in records:
            raise ProcessNotOwned(run_id)
        return records[run_id]

    def start(**kwargs):
        launches.append(kwargs)
        records[kwargs["run_id"]] = {"executor": music.EXECUTOR, "alive": True}
        return records[kwargs["run_id"]]

    manager = SimpleNamespace(inspect=inspect, start=start)
    body = request()
    first = music.start(manager, body)
    assert music.start(manager, body) == first
    assert len(launches) == 1
    launch = launches[0]
    assert launch["argv"][:3] == [str(tmp_path / "python"), "-m", "ai_station_runner.music_entry"]
    assert body.caption not in launch["argv"]
    assert launch["env"]["CUDA_VISIBLE_DEVICES"] == "7"
    assert launch["env"]["HF_HUB_OFFLINE"] == "1"
    assert launch["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert "HF_TOKEN" not in launch["env"] and "SOME_SECRET" not in launch["env"]
    changed = body.model_copy(update={"caption": "Different prompt"})
    with pytest.raises(ValueError, match="different music request"):
        music.start(manager, changed)
    assert len(launches) == 1


def test_music_requires_both_permissions_before_writing_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    with pytest.raises(PermissionError):
        music.start(None, request(permissions=["filesystem_read"]))
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("event", ["socket.connect", "socket.sendto", "socket.getaddrinfo"])
def test_inference_network_attempts_are_rejected(event):
    with pytest.raises(PermissionError, match="network"):
        music_entry.deny_network(event, ())
    music_entry.deny_network("open", ())


@pytest.mark.parametrize("invalid", [False, True])
def test_entry_publishes_only_valid_owned_audio(tmp_path, monkeypatch, invalid):
    body = request()
    root = tmp_path / "runtime/music" / str(body.run_id)
    root.mkdir(parents=True)
    (root / "request.json").write_text(body.model_dump_json())
    model = tmp_path / "model"
    model.mkdir()
    monkeypatch.setattr(music_entry, "generate", lambda *args: "fake samples")
    monkeypatch.setattr(music_entry, "write_pcm", lambda tensor, path: pcm(path, truncated=invalid))
    monkeypatch.setattr(music_entry.signal, "alarm", lambda seconds: None)
    output = tmp_path / "artifacts" / str(body.run_id)[:2] / str(body.run_id)[2:4] / f"{body.run_id}.wav"
    if invalid:
        with pytest.raises(ValueError, match="truncated"):
            music_entry.execute(str(body.run_id), tmp_path, model, tmp_path / "source")
        assert not output.exists()
    else:
        music_entry.execute(str(body.run_id), tmp_path, model, tmp_path / "source")
        assert music_protocol.wav_metadata(output)["duration_seconds"] == 10
        with pytest.raises(ValueError, match="exists"):
            music_entry.execute(str(body.run_id), tmp_path, model, tmp_path / "source")


def test_upstream_bridge_disables_download_sync_and_additional_language_model(tmp_path, monkeypatch):
    calls = {}
    view = tmp_path / "checkpoints"

    class Handler:
        def initialize_service(self, **kwargs):
            calls["initialization"] = kwargs
            assert self._get_project_root() == str(tmp_path)
            assert self._ensure_models_present(checkpoint_path=view, config_path="acestep-v15-turbo") is None
            with pytest.raises(ValueError):
                self._ensure_models_present(checkpoint_path=view, config_path="unreviewed-model")
            self._sync_model_code_if_needed("acestep-v15-turbo", view)
            with pytest.raises(ValueError):
                self._sync_model_code_if_needed("unreviewed-model", view)
            return "ready", True

    def generate(handler, lm, params, config, save_dir):
        assert lm is None and save_dir is None
        calls["params"], calls["config"] = params, config
        return SimpleNamespace(
            success=True, audios=[{"sample_rate": 48000, "params": {"seed": 42}, "tensor": "samples"}]
        )

    monkeypatch.setitem(sys.modules, "acestep.handler", SimpleNamespace(AceStepHandler=Handler))
    monkeypatch.setitem(
        sys.modules,
        "acestep.inference",
        SimpleNamespace(
            GenerationParams=lambda **kwargs: kwargs,
            GenerationConfig=lambda **kwargs: kwargs,
            generate_music=generate,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "acestep.model_downloader", SimpleNamespace(_check_code_mismatch=lambda *args: [])
    )
    monkeypatch.setattr(music_entry, "checkpoint_view", lambda *args: view)
    hooks = []
    monkeypatch.setattr(music_entry.sys, "addaudithook", hooks.append)
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", "not-selected-by-the-caller")
    result = music_entry.generate(
        request().model_dump(mode="json"), tmp_path / "model", view, tmp_path / "source", tmp_path
    )
    assert result == "samples"
    assert hooks == [music_entry.deny_network]
    assert calls["initialization"]["offload_to_cpu"] is True
    assert calls["initialization"]["offload_dit_to_cpu"] is True
    assert calls["initialization"]["compile_model"] is False
    assert calls["params"]["thinking"] is False
    assert calls["params"]["use_cot_metas"] is False
    assert calls["params"]["use_cot_caption"] is False
    assert calls["params"]["lyrics"] == "[Instrumental]"
    assert calls["config"]["batch_size"] == 1
    assert calls["config"]["use_random_seed"] is False


def test_manifest_identity_matches_the_committed_installer():
    path = Path(__file__).resolve().parents[2] / "config/music/ace-step-1.5-turbo.json"
    manifest = json.loads(path.read_text())
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == music_protocol.MANIFEST_SHA256
    assert manifest["revision"] == music_protocol.MODEL_REVISION
    assert manifest["code_revision"] == music_protocol.CODE_REVISION
