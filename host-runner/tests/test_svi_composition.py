"""The recurrent profile composes in its own CPU environment, never a 5B fallback."""

import json
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import (
    media_compose,
    media_compose_job,
    memory_scope,
    svi_environment,
    video_environment,
    video_selection,
)
from ai_station_runner import video_composition_runtime as runtimes
from fastapi import HTTPException
from pydantic import ValidationError
from test_media_compose import clip


def observation():
    return {"profile": svi_environment.PROFILE, "manifest_sha256": "a" * 64, "environment_id": "b" * 64}


def request(root):
    clips = [clip(root, "one.mp4", frames=81, fps=15), clip(root, "two.mp4", frames=81, fps=15)]
    clips[1].update(first_frame=4, frames=69)
    return media_compose.ComposeRequest(
        run_id=uuid4(),
        deadline_at=time.time() + 60,
        managed_runtime=observation(),
        clips=clips,
        fps=15,
        width=128,
        height=128,
        target_frames=150,
        permissions=["filesystem_read", "workspace_write"],
    )


def test_svi_dispatch_selects_exact_engine_even_with_external_five_b_configuration(tmp_path, monkeypatch):
    body = request(tmp_path)
    settings = SimpleNamespace(
        host_data_dir=lambda: tmp_path, video_python="/external/5b/python", mmaudio_enabled=False
    )
    monkeypatch.setattr(media_compose, "get_settings", lambda: settings)
    monkeypatch.setattr(svi_environment, "QUALIFIED", True)
    calls = []

    def resolve(root, runtime):
        assert root == tmp_path and runtime == observation()
        calls.append(runtime)
        return {"managed": True, "video_python": sys.executable}

    monkeypatch.setattr(svi_environment, "resolve_public", resolve)
    monkeypatch.setattr(video_selection, "selection", lambda *a: pytest.fail("SVI entered 5B selection"))
    monkeypatch.setattr(memory_scope, "scope_prefix", lambda identity, ram: ["fixed-scope", str(ram)])
    monkeypatch.setattr(memory_scope, "scope_environment", lambda: {})
    manager = SimpleNamespace(start=lambda **values: values)
    started = media_compose.start_composition(manager, body)
    assert calls == [observation()]
    assert started["argv"][:3] == ["fixed-scope", "4096", sys.executable]
    assert started["env"]["CUDA_VISIBLE_DEVICES"] == ""
    assert started["executor"] == "media_compose"
    assert (
        json.loads((started["cwd"] / "request.json").read_text())["request"]["managed_runtime"]
        == observation()
    )


@pytest.mark.parametrize("reason", ["unqualified", "missing", "changed"])
def test_svi_dispatch_refuses_unavailable_engine_without_external_fallback(tmp_path, monkeypatch, reason):
    body = request(tmp_path)
    monkeypatch.setattr(
        media_compose, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: tmp_path)
    )
    monkeypatch.setattr(svi_environment, "QUALIFIED", reason != "unqualified")
    monkeypatch.setattr(video_selection, "selection", lambda *a: pytest.fail("Unrequested 5B fallback"))

    def resolve(*args):
        if reason == "missing":
            raise FileNotFoundError("missing engine")
        raise ValueError("changed receipt")

    monkeypatch.setattr(svi_environment, "resolve_public", resolve)
    manager = SimpleNamespace(start=lambda **kw: pytest.fail("Unavailable engine dispatched"))
    with pytest.raises(HTTPException) as exc:
        media_compose.start_composition(manager, body)
    assert exc.value.status_code == 409
    assert not (tmp_path / "runs").exists()


def test_svi_offline_composition_preserves_actual_fifteen_fps_and_context_trimming(tmp_path, monkeypatch):
    body = request(tmp_path)
    calls = []
    monkeypatch.setattr(media_compose_job.sys, "base_prefix", str(tmp_path / "owned/python"))
    monkeypatch.setattr(svi_environment, "resolve_public", lambda *args: {"environment": tmp_path / "owned"})
    monkeypatch.setattr(video_environment, "resolve_public", lambda *a: pytest.fail("SVI used 5B runtime"))
    monkeypatch.setattr(memory_scope, "require_scope", lambda identity, ram: calls.append((identity, ram)))
    monkeypatch.setattr(media_compose_job.signal, "setitimer", lambda *a: None)
    monkeypatch.setattr(media_compose_job.sys, "addaudithook", lambda *a: None)
    output = tmp_path / "artifacts/result.mp4"
    result = media_compose_job.compose(
        {"root": str(tmp_path), "output": str(output), "request": body.model_dump(mode="json")}
    )
    assert calls == [(str(body.run_id), 4096)]
    assert result["verified"] and result["frames"] == 150
    assert result["fps"] == 15 and result["duration_seconds"] == 10
    assert result["video_encoding"]["crf"] == 18


def test_svi_child_rejects_foreign_python_before_scope_or_decode(tmp_path, monkeypatch):
    monkeypatch.setattr(svi_environment, "resolve_public", lambda *a: {"environment": tmp_path})
    monkeypatch.setattr(
        memory_scope, "require_scope", lambda *a: pytest.fail("Foreign interpreter reached scope")
    )
    with pytest.raises(ValueError, match="exact frozen"):
        media_compose_job.compose({"root": str(tmp_path), "request": {"managed_runtime": observation()}})


@pytest.mark.parametrize(
    "runtime", [None, {}, {"profile": "unknown"}, {**observation(), "environment_id": "../private"}]
)
def test_closed_runtime_identity_cannot_choose_a_generic_composition_environment(tmp_path, runtime):
    with pytest.raises((ValueError, OSError)):
        runtimes.resolve_public(tmp_path, runtime)


def test_svi_compose_request_cannot_supply_paths_or_arbitrary_profiles(tmp_path):
    values = request(tmp_path).model_dump(mode="json")
    for change in [{"profile": "unknown"}, {"python": "/tmp/arbitrary"}, {"operation_id": str(uuid4())}]:
        with pytest.raises(ValidationError):
            media_compose.ComposeRequest.model_validate(
                {**values, "managed_runtime": {**observation(), **change}}
            )
