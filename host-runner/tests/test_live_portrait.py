import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import live_environment
from ai_station_runner import live_portrait_environment as portrait
from ai_station_runner.live_contract import LiveRequest
from pydantic import ValidationError
from test_live_session import request


def portrait_request(**changes):
    return request(
        mode="portrait",
        managed_runtime={
            "profile": portrait.PROFILE,
            "manifest_sha256": portrait.MANIFEST,
            "environment_id": "b" * 64,
        },
        **changes,
    )


def test_portrait_recipe_is_a_bounded_extension_not_a_second_python_install():
    frozen = portrait.recipe()
    assert frozen["base_profile"] == live_environment.PROFILE
    assert frozen["base_manifest_sha256"] == live_environment.MANIFEST
    assert {v["kind"] for v in frozen["inputs"]} == {"model", "sdk"}
    assert all(v["size_bytes"] >= 1 for v in frozen["inputs"])
    assert len([v for v in frozen["inputs"] if v["kind"] == "model"]) == 5
    assert sum(v["size_bytes"] for v in frozen["inputs"]) < 550 * 1024**2
    assert len({v["filename"] for v in frozen["inputs"]}) == len(frozen["inputs"])


def test_legacy_requests_keep_face_swap_and_portrait_requires_its_own_runtime():
    assert LiveRequest.model_validate(request()).mode == "face_swap"
    assert LiveRequest.model_validate(portrait_request()).mode == "portrait"
    for body in (
        request(mode="portrait"),
        portrait_request(image=None, voice=request()["image"]),
        {**portrait_request(), "mode": "face_swap"},
        request(mode="arbitrary"),
    ):
        with pytest.raises(ValidationError):
            LiveRequest.model_validate(body)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    # Fake files exercise the real ownership/layout validator without model inference.
    inputs = []
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    for kind, target in (("model", "motion.pth"), ("sdk", "src/modules/model.py")):
        data = (kind + " fixed input").encode()
        sha = hashlib.sha256(data).hexdigest()
        p = store / sha
        p.write_bytes(data)
        p.chmod(0o444)
        inputs.append(
            {
                "kind": kind,
                "role": "portrait_motion",
                "filename": target.rsplit("/", 1)[-1],
                "target": target,
                "sha256": sha,
                "size_bytes": len(data),
            }
        )
    base = {
        "profile": live_environment.PROFILE,
        "manifest_sha256": live_environment.MANIFEST,
        "operation_id": str(uuid4()),
    }
    folder = tmp_path / "runtime" / live_environment.NAMESPACE
    folder.mkdir(parents=True)
    (folder / "active.json").write_text(json.dumps(base))
    (folder / "active.json").chmod(0o600)
    frozen = {"inputs": inputs, "base_manifest_sha256": live_environment.MANIFEST}
    monkeypatch.setattr(portrait, "recipe", lambda: frozen)
    monkeypatch.setattr(
        portrait.base,
        "resolve",
        lambda root, observation: {
            "python": "unused-fake-python",
            "environment": tmp_path / "base",
            "observation": observation,
        },
    )
    monkeypatch.setattr(portrait, "command", lambda *a, **k: None)
    for path in tmp_path.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
    operation = str(uuid4())
    portrait.prepare(tmp_path, operation)
    observation = {
        "profile": portrait.PROFILE,
        "manifest_sha256": portrait.MANIFEST,
        "operation_id": operation,
    }
    public = portrait.remember(tmp_path, observation)
    return tmp_path, observation, public


def test_extension_binds_original_base_even_after_active_base_selection_changes(prepared):
    root, observation, public = prepared
    original = portrait.resolve_public(root, public)
    active = root / "runtime" / live_environment.NAMESPACE / "active.json"
    active.write_text(json.dumps({"unrelated": "different active runtime"}))
    restored = portrait.resolve_public(root, public)
    assert restored["python"] == original["python"]
    assert restored["portrait_environment"] == original["portrait_environment"]
    assert restored["observation"] == observation


@pytest.mark.parametrize("tamper", ["bytes", "extra_code", "symlink", "hardlink", "writable"])
def test_portrait_rejects_changed_or_injected_executable_sdk(prepared, tamper):
    root, observation, public = prepared
    folder = portrait.resolve_public(root, public)["portrait_environment"]
    source = folder / "sdk/src/modules/model.py"
    if tamper == "bytes":
        source.chmod(0o600)
        source.write_bytes(b"changed")
    elif tamper == "extra_code":
        (folder / "sdk/src/__init__.py").write_text("raise RuntimeError()")
    elif tamper == "writable":
        source.chmod(0o600)
    else:
        other = root / "untrusted.py"
        other.write_bytes(source.read_bytes())
        other.chmod(0o400)
        source.unlink()
        if tamper == "symlink":
            source.symlink_to(other)
        else:
            __import__("os").link(other, source)
    # Rewriting a self-reported source digest cannot admit extra executable code.
    if tamper == "extra_code":
        ready = folder / "ready.json"
        v = json.loads(ready.read_text())
        v["source_manifest_sha256"] = live_environment.source_manifest(folder)
        ready.write_text(json.dumps(v))
    with pytest.raises(ValueError):
        portrait.resolve_public(root, public)


def test_portrait_tracking_loss_never_returns_camera_pixels():
    from unittest.mock import Mock

    from ai_station_runner.live_face_engine import FaceTrackingError
    from ai_station_runner.live_portrait_engine import PortraitEngine

    engine = PortraitEngine.__new__(PortraitEngine)
    engine.reference = object()
    engine._crop = Mock(side_effect=FaceTrackingError("No face"))
    engine._tensor = Mock()
    engine.networks = {"spade_generator": Mock()}
    with pytest.raises(FaceTrackingError):
        engine.transform(object())
    engine._tensor.assert_not_called()
    engine.networks["spade_generator"].assert_not_called()


def test_portrait_preparation_stop_fences_late_start(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from ai_station_runner import live_portrait_prepare as preparation
    from ai_station_runner import runtime_install
    from ai_station_runner.processes import ProcessManager

    settings = SimpleNamespace(host_data_dir=lambda: tmp_path)
    monkeypatch.setattr(preparation, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_install, "get_settings", lambda: settings)
    identity = uuid4()
    permissions = ["manage_models", "network_read", "workspace_write"]
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    try:
        selection = preparation.Selection(profile=portrait.PROFILE, permissions=permissions)
        stopped = preparation.controller().cancel(manager, identity, selection)
        assert stopped["status"] == "canceled" and not stopped["alive"]
        body = preparation.Preparation(
            run_id=identity,
            profile=portrait.PROFILE,
            permissions=permissions,
            manifest_sha256=portrait.MANIFEST,
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        late = preparation.controller().start(manager, body)
        assert late["status"] == "canceled" and late["process"] is None
        assert preparation.journal(identity)["cancellation_requested"]
    finally:
        manager.shutdown()
