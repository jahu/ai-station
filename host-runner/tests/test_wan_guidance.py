"""Fixed guidance contract and readiness checks without Torch, models or a GPU."""

import hashlib
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import video
from ai_station_runner.video import VideoRequest
from ai_station_runner.wan_guidance import apg_observation, apply_guidance
from ai_station_runner.wan_motion import profile_key
from fastapi import HTTPException
from pydantic import ValidationError

APG_SOURCE = b"""raise RuntimeError('Readiness must never execute installed code')
class APG:
    @classmethod
    def execute(cls, model, eta, norm_threshold, momentum):
        pass
"""
OBSERVATION = {"size_bytes": 100, "sha256": "f" * 64}


def installed(tmp_path, source=APG_SOURCE):
    path = tmp_path / "comfy_extras/nodes_apg.py"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(source)
    return {"comfy_dir": tmp_path}


def body():
    return {
        "run_id": str(uuid4()),
        "prompt": "Lake",
        "gpu": 0,
        "permissions": ["filesystem_read", "workspace_write"],
        "continuation": {"relative_path": "artifacts/prior.mp4", "sha256": "a" * 64, "size_bytes": 100},
    }


def test_readiness_hashes_bounded_compatible_source_without_executing_it(tmp_path):
    observed = apg_observation(installed(tmp_path))
    assert observed == {"size_bytes": len(APG_SOURCE), "sha256": hashlib.sha256(APG_SOURCE).hexdigest()}


def test_worker_serialized_paths_preserve_the_native_observation(tmp_path):
    paths = installed(tmp_path)
    assert apg_observation({"comfy_dir": str(paths["comfy_dir"])}) == apg_observation(paths)


@pytest.mark.parametrize(
    "source",
    [
        b"not python !",
        b"class APG: pass",
        APG_SOURCE.replace(b"norm_threshold", b"other"),
        APG_SOURCE.replace(b"@classmethod", b"# unbound method"),
        b"#" * 65537,
    ],
)
def test_incompatible_or_oversized_runtime_does_not_advertise_guidance(tmp_path, source):
    assert apg_observation(installed(tmp_path, source)) is None


def test_missing_guidance_cannot_launch_or_create_native_work(tmp_path, monkeypatch):
    assert apg_observation({"comfy_dir": tmp_path}) is None
    monkeypatch.setattr(video, "profile", lambda: {"comfy_dir": tmp_path})
    manager = SimpleNamespace(start=lambda **_: pytest.fail("Unavailable guidance must not launch"))
    with pytest.raises(HTTPException) as error:
        video.start_video(
            manager, VideoRequest(**body(), continuation_guidance="apg_v1", guidance_observation=OBSERVATION)
        )
    assert error.value.status_code == 409
    assert not (tmp_path / "runs").exists()


def test_legacy_serialization_stays_identical_and_guided_requests_keep_the_recipe():
    legacy = VideoRequest(**body())
    explicit = VideoRequest(**{**body(), "run_id": legacy.run_id}, continuation_guidance="standard")
    assert legacy.model_dump(mode="json") == explicit.model_dump(mode="json")
    assert "continuation_guidance" not in legacy.model_dump()
    guided = VideoRequest(**body(), continuation_guidance="apg_v1", guidance_observation=OBSERVATION)
    assert guided.model_dump()["continuation_guidance"] == "apg_v1" and guided.continuation_frames == 17


@pytest.mark.parametrize(
    "change",
    [
        {"continuation": None},
        {
            "motion_context": {
                "relative_path": "artifacts/raw.safetensors",
                "sha256": "b" * 64,
                "size_bytes": 100,
            }
        },
    ],
)
def test_projected_guidance_requires_owned_pixel_context_not_raw_tail(change):
    with pytest.raises(ValidationError, match="preceding video pixels"):
        VideoRequest(**{**body(), **change}, continuation_guidance="apg_v1", guidance_observation=OBSERVATION)


def test_guidance_runtime_change_is_rejected_before_process_or_work_creation(tmp_path, monkeypatch):
    paths = installed(tmp_path)
    before = apg_observation(paths)
    installed(tmp_path, APG_SOURCE + b"\n# changed implementation\n")
    monkeypatch.setattr(video, "profile", lambda: paths)
    manager = SimpleNamespace(start=lambda **_: pytest.fail("Changed guidance must not launch"))
    request = VideoRequest(**body(), continuation_guidance="apg_v1", guidance_observation=before)
    with pytest.raises(HTTPException, match="changed after") as error:
        video.start_video(manager, request)
    assert error.value.status_code == 409
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("method,observation", [("apg_v1", None), ("standard", OBSERVATION)])
def test_guidance_implementation_snapshot_cannot_be_omitted_or_added_to_legacy(method, observation):
    with pytest.raises(ValidationError, match="frozen implementation observation"):
        VideoRequest(**body(), continuation_guidance=method, guidance_observation=observation)


@pytest.mark.parametrize("method", ["arbitrary-node", True, 1, None, {"method": "apg_v1"}])
def test_native_recipe_is_a_fixed_enum(method):
    with pytest.raises(ValidationError):
        VideoRequest(**body(), continuation_guidance=method)


def test_fixed_guidance_calls_the_builtin_recipe_and_standard_does_not_import(monkeypatch):
    original, patched, calls = object(), object(), []
    assert apply_guidance(original) is original

    class APG:
        @classmethod
        def execute(cls, model, eta, norm_threshold, momentum):
            calls.append((model, eta, norm_threshold, momentum))
            return (patched,)

    monkeypatch.setitem(sys.modules, "comfy_extras", ModuleType("comfy_extras"))
    monkeypatch.setitem(sys.modules, "comfy_extras.nodes_apg", SimpleNamespace(APG=APG))
    assert apply_guidance(original, "apg_v1") is patched
    assert calls == [(original, 0.0, 5.0, 0.0)]
    with pytest.raises(ValueError, match="fixed Wan guidance"):
        apply_guidance(original, "custom")


def test_guided_checkpoints_cannot_masquerade_as_legacy_or_a_different_runtime(tmp_path):
    paths = installed(tmp_path)
    for key in ("wan_model", "wan_text_encoder", "wan_vae"):
        paths[key] = tmp_path / key
        paths[key].write_bytes(b"model observation")
    standard = profile_key(paths, "bounded_11g")
    assert standard == profile_key(paths, "bounded_11g", "standard")
    guided = profile_key(paths, "bounded_11g", "apg_v1")
    assert guided != standard
    installed(tmp_path, APG_SOURCE + b"\n# changed installation\n")
    assert guided != profile_key(paths, "bounded_11g", "apg_v1")
