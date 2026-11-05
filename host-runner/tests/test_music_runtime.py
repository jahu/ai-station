"""Opaque shared identities over fake prepared engines; no installed SDK or GPU."""

import json
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest
from ai_station_runner import music_runtime
from test_music_environment import fixture as fixture


@pytest.fixture
def engine(fixture):
    from ai_station_runner import music_environment

    root, items, _ = fixture
    result = music_environment.prepare(root, str(uuid4()))
    folder = root / result["relative_path"]
    (folder / "python/bin/python3.12").chmod(0o700)
    observation = {k: result[k] for k in ("profile", "manifest_sha256", "operation_id")}
    pointer = folder.parent.parent / "active.json"
    pointer.write_text(json.dumps(observation))
    pointer.chmod(0o600)
    from types import SimpleNamespace

    return (
        SimpleNamespace(host_data_dir=lambda: root),
        folder,
        pointer,
        root / "models/store" / items[-1]["sha256"],
    )


def test_existing_active_engine_resolves_without_disclosing_preparation_or_mutating_storage(engine):
    settings, folder, pointer, _ = engine
    private = json.loads(pointer.read_text())
    public = music_runtime.public_observation(private)
    assert set(public) == {"profile", "manifest_sha256", "environment_id"}
    assert private["operation_id"] not in json.dumps(public)
    assert music_runtime.resolve_public(settings.host_data_dir(), public)["environment"] == folder
    assert not (pointer.parent / "identities").exists()


def test_explicit_adoption_preserves_both_original_opaque_bindings_after_activation(engine):
    settings, folder, pointer, _ = engine
    root = settings.host_data_dir()
    previous = json.loads(pointer.read_text())
    old_public = music_runtime.public_observation(previous)
    new_operation = str(uuid4())
    new_folder = folder.parent / new_operation
    shutil.copytree(folder, new_folder, symlinks=True)
    (new_folder / "venv/bin/python").unlink()
    (new_folder / "venv/bin/python").symlink_to(new_folder / "python/bin/python3.12")
    selected = {**previous, "operation_id": new_operation}
    (new_folder / "ready.json").write_text(
        json.dumps(
            {
                **selected,
                "relative_path": new_folder.relative_to(root).as_posix(),
                "environment_prepared": True,
            }
        )
    )
    music_runtime.before_adoption(root, selected)
    pointer.write_text(json.dumps(selected))
    public = music_runtime.public_observation(selected)
    assert public != old_public
    assert music_runtime.resolve_public(root, old_public)["environment"] == folder
    assert music_runtime.resolve_public(root, public)["environment"] == new_folder
    assert music_runtime.remember(root, selected) == public


@pytest.mark.parametrize("change", ["path", "extra", "manifest", "profile", "unmapped"])
def test_untrusted_public_coordinates_cannot_choose_an_environment(engine, change):
    settings, _, pointer, _ = engine
    public = music_runtime.public_observation(json.loads(pointer.read_text()))
    if change == "path":
        public["environment_id"] = "../../etc"
    elif change == "extra":
        public["operation_id"] = str(uuid4())
    elif change == "manifest":
        public["manifest_sha256"] = "f" * 64
    elif change == "profile":
        public["profile"] = "other"
    else:
        public["environment_id"] = "a" * 64
    with pytest.raises(ValueError):
        music_runtime.resolve_public(settings.host_data_dir(), public)


@pytest.mark.parametrize("change", ["writable", "link", "identity", "binary", "model"])
def test_modified_or_escaped_identity_engine_or_models_are_rejected(engine, tmp_path, change):
    settings, folder, pointer, weight = engine
    root = settings.host_data_dir()
    private = json.loads(pointer.read_text())
    public = music_runtime.remember(root, private)
    mapping = pointer.parent / "identities" / (public["environment_id"] + ".json")
    if change == "writable":
        mapping.chmod(0o666)
    elif change == "link":
        saved = tmp_path / "map.json"
        mapping.rename(saved)
        mapping.symlink_to(saved)
    elif change == "identity":
        mapping.write_text(json.dumps({**private, "operation_id": str(uuid4())}))
    elif change == "binary":
        python = folder / "venv/bin/python"
        python.unlink()
        python.symlink_to(sys.executable)
    elif change == "cache":
        cache = folder / "cache"
        cache.rmdir()
        external = tmp_path / "external-cache"
        external.mkdir()
        cache.symlink_to(external, target_is_directory=True)
    else:
        weight.chmod(0o600)
    with pytest.raises((OSError, ValueError)):
        music_runtime.resolve_public(root, public)


def test_offline_runtime_resolution_never_imports_the_http_or_inference_stack():
    code = """
import importlib.abc,sys
class NoHeavy(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','fastapi','uvicorn','acestep'}:
   raise ModuleNotFoundError('Offline identity resolution needs no HTTP/inference packages')
sys.meta_path.insert(0,NoHeavy())
from ai_station_runner.music_runtime import public_observation,PROFILE
assert set(public_observation({'profile':PROFILE,'manifest_sha256':'a'*64,'operation_id':'local'}))=={'profile','manifest_sha256','environment_id'}
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)


@pytest.mark.parametrize("field,value", [("profile", None), ("manifest_sha256", []), ("operation_id", 3)])
def test_malformed_private_observation_is_not_a_runtime_coordinate(engine, field, value):
    settings, _, pointer, _ = engine
    private = json.loads(pointer.read_text())
    with pytest.raises(ValueError, match="exact prepared"):
        music_runtime.resolve(settings.host_data_dir(), {**private, field: value})


def test_selected_checkpoint_and_owned_launch_do_not_follow_later_defaults(engine, monkeypatch):
    import hashlib
    import time
    from types import SimpleNamespace

    from ai_station_runner import memory_scope, music, music_checkpoints
    from ai_station_runner.music_runtime_schema import CheckpointSource
    from ai_station_runner.processes import ProcessNotOwned
    from test_music_checkpoints import checkpoint

    settings, folder, pointer, _ = engine
    root = settings.host_data_dir()
    private = json.loads(pointer.read_text())
    runtime = music_runtime.remember(root, private)
    content = checkpoint()
    sha = hashlib.sha256(content).hexdigest()
    path = root / "models/store" / sha
    path.write_bytes(content)
    path.chmod(0o400)
    expected = {
        "runtime_manifest_sha256": private["manifest_sha256"],
        "tensor_count": 2,
        "schema_sha256": music_checkpoints.fingerprint({"diffusion.weight": [2, 2], "diffusion.bias": [2]}),
        "allowed_dtypes": ["BF16"],
        "runtime_profile": private["profile"],
        "role": "ace_step15_turbo_diffusion",
        "notice": "Synthetic descriptor only",
    }
    monkeypatch.setattr(music_checkpoints, "recipe", lambda profile: expected)
    source = CheckpointSource(
        profile=music_checkpoints.PROFILE,
        relative_path="models/store/" + sha,
        sha256=sha,
        size_bytes=len(content),
        mtime=path.stat().st_mtime,
        schema_sha256=expected["schema_sha256"],
    )
    chosen = music_checkpoints.selected_environment(root, source, runtime, verify_weights=True)
    assert chosen["checkpoint_path"] == path
    monkeypatch.setattr(music, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: root))
    monkeypatch.setattr(music, "selected_source", lambda *args: chosen)
    monkeypatch.setattr(music, "collect", lambda root: {"gpus": [{"index": 7, "memory_total_mib": 12288}]})
    monkeypatch.setattr(memory_scope, "scope_prefix", lambda identity, limit: ["owned-scope", str(limit)])
    monkeypatch.setattr(memory_scope, "scope_environment", lambda: {})
    calls = []

    class Manager:
        def inspect(self, identity):
            if not calls:
                raise ProcessNotOwned(identity)
            return {"executor": music.EXECUTOR, "run_id": identity, "alive": True}

        def start(self, **values):
            calls.append(values)
            return self.inspect(values["run_id"])

    body = music.MusicRequest(
        run_id=uuid4(),
        caption="Piano",
        duration_seconds=10,
        seed=3,
        gpu=7,
        permissions=sorted(music.PERMISSIONS),
        checkpoint=source,
        managed_runtime=runtime,
        runtime_manifest_sha256=private["manifest_sha256"],
        deadline_at=time.time() + 60,
    )
    manager = Manager()
    music.start(manager, body)
    assert calls[0]["argv"][:2] == ["owned-scope", "12288"]
    assert calls[0]["argv"][2] == str(folder / "venv/bin/python")
    assert calls[0]["env"]["CUDA_VISIBLE_DEVICES"] == "7" and calls[0]["deadline_at"] == body.deadline_at

    def changed(*args):
        raise AssertionError("Owned inspection must not resolve a different current model")

    monkeypatch.setattr(music, "selected_source", changed)
    assert music.start(manager, body)["alive"] and len(calls) == 1
    path.chmod(0o600)
    with pytest.raises(ValueError):
        music_checkpoints.selected_environment(root, source, runtime, verify_weights=True)
