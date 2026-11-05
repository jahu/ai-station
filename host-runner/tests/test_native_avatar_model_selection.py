"""Selected readiness is an exact, read-only, private engine query."""

from types import SimpleNamespace

import pytest
from ai_station_runner import avatar_checkpoints, sonic_runtime
from ai_station_runner import avatar_model_selection as selection
from fastapi import HTTPException
from pydantic import ValidationError
from test_selected_avatar_checkpoint import selected as selected
from test_sonic_jobs import prepared as prepared


def body(selected):
    request, _, _, _, managed = selected
    return selection.ModelSelection(
        checkpoint=request.checkpoint,
        managed_runtime={
            "profile": avatar_checkpoints.RUNTIME,
            "manifest_sha256": managed["observation"]["manifest_sha256"],
            "environment_id": "b" * 64,
        },
        permissions=["filesystem_read"],
    )


def test_unqualified_selection_is_unavailable_and_never_resolves_or_loads_weights(selected, monkeypatch):
    monkeypatch.setattr(avatar_checkpoints, "INFERENCE_QUALIFIED", False)
    monkeypatch.setattr(
        avatar_checkpoints, "selected_environment", lambda *a: pytest.fail("No preparation or load")
    )
    assert not selection.capabilities(body(selected))["available"]


def test_exact_engine_probe_retains_checkpoint_without_exposing_setup_paths(selected, monkeypatch):
    _, manager, _, _, _ = selected
    monkeypatch.setattr(avatar_checkpoints, "INFERENCE_QUALIFIED", True)
    monkeypatch.setattr(
        selection, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: manager.data_dir)
    )
    monkeypatch.setattr(selection, "collect", lambda root: {"memory": {"total_mib": 32768}})

    def caps(identity):
        assert identity == "b" * 64
        return {
            "available": True,
            "recipe": {"id": "sonic_whole_768_v1", "observation": "c" * 64, "environment_id": identity},
            "configuration_source": "managed",
        }

    monkeypatch.setattr(sonic_runtime, "capabilities", caps)
    request = body(selected)
    result = selection.capabilities(request)
    assert result["available"] and result["checkpoint"] == request.checkpoint
    assert result["managed_runtime"] == request.managed_runtime.model_dump(mode="json")
    assert "operation_id" not in str(result) and str(manager.data_dir) not in str(result)
    monkeypatch.setattr(selection, "collect", lambda root: {"memory": {"total_mib": 8192}})
    assert not selection.capabilities(request)["available"]


def test_query_requires_read_permission_and_closed_public_engine_coordinates(selected):
    value = body(selected).model_dump(mode="json")
    with pytest.raises(HTTPException) as denied:
        selection.capabilities(selection.ModelSelection.model_validate({**value, "permissions": []}))
    assert denied.value.status_code == 403
    for change in (
        {"command": "anything"},
        {"managed_runtime": {**value["managed_runtime"], "operation_id": "private"}},
        {"managed_runtime": {**value["managed_runtime"], "manifest_sha256": "f" * 64}},
        {"checkpoint": {**value["checkpoint"], "relative_path": "/etc/passwd"}},
    ):
        with pytest.raises(ValidationError):
            selection.ModelSelection.model_validate({**value, **change})
