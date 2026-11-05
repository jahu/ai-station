"""Opaque shared identities over fake prepared engines; no installed SDK or GPU."""

import json
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest
from ai_station_runner import speech_runtime
from test_speech_selection import prepared as prepared


@pytest.fixture
def engine(prepared):
    settings, _, _, _ = prepared
    # Match the private native installer's directories; the legacy selector
    # fixture itself intentionally imposes no directory-mode policy.
    for path in (settings.host_data_dir() / "runtime", settings.host_data_dir() / "runtime/speech"):
        path.chmod(0o700)
    return prepared


def test_existing_active_engine_resolves_without_disclosing_preparation_or_mutating_storage(engine):
    settings, folder, pointer, _ = engine
    private = json.loads(pointer.read_text())
    public = speech_runtime.public_observation(private)
    assert set(public) == {"profile", "manifest_sha256", "environment_id"}
    assert private["operation_id"] not in json.dumps(public)
    assert speech_runtime.resolve_public(settings.host_data_dir(), public)["environment"] == folder
    assert not (pointer.parent / "identities").exists()


def test_explicit_adoption_preserves_both_original_opaque_bindings_after_activation(engine):
    settings, folder, pointer, _ = engine
    root = settings.host_data_dir()
    previous = json.loads(pointer.read_text())
    old_public = speech_runtime.public_observation(previous)
    new_operation = str(uuid4())
    new_folder = folder.parent / new_operation
    shutil.copytree(folder, new_folder, symlinks=True)
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
    speech_runtime.before_adoption(root, selected)
    pointer.write_text(json.dumps(selected))
    public = speech_runtime.public_observation(selected)
    assert public != old_public
    assert speech_runtime.resolve_public(root, old_public)["environment"] == folder
    assert speech_runtime.resolve_public(root, public)["environment"] == new_folder
    assert speech_runtime.remember(root, selected) == public


@pytest.mark.parametrize("change", ["path", "extra", "manifest", "profile", "unmapped"])
def test_untrusted_public_coordinates_cannot_choose_an_environment(engine, change):
    settings, _, pointer, _ = engine
    public = speech_runtime.public_observation(json.loads(pointer.read_text()))
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
        speech_runtime.resolve_public(settings.host_data_dir(), public)


@pytest.mark.parametrize("change", ["writable", "link", "identity", "binary", "model", "cache"])
def test_modified_or_escaped_identity_engine_or_models_are_rejected(engine, tmp_path, change):
    settings, folder, pointer, weight = engine
    root = settings.host_data_dir()
    private = json.loads(pointer.read_text())
    public = speech_runtime.remember(root, private)
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
        speech_runtime.resolve_public(root, public)


def test_offline_runtime_resolution_never_imports_the_http_or_inference_stack():
    code = """
import importlib.abc,sys
class NoHeavy(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','fastapi','uvicorn','chatterbox'}:
   raise ModuleNotFoundError('Offline identity resolution needs no HTTP/inference packages')
sys.meta_path.insert(0,NoHeavy())
from ai_station_runner.speech_runtime import public_observation,PROFILE
assert set(public_observation({'profile':PROFILE,'manifest_sha256':'a'*64,'operation_id':'local'}))=={'profile','manifest_sha256','environment_id'}
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)


@pytest.mark.parametrize("field,value", [("profile", None), ("manifest_sha256", []), ("operation_id", 3)])
def test_malformed_private_observation_is_not_a_runtime_coordinate(engine, field, value):
    settings, _, pointer, _ = engine
    private = json.loads(pointer.read_text())
    with pytest.raises(ValueError, match="exact prepared"):
        speech_runtime.resolve(settings.host_data_dir(), {**private, field: value})
