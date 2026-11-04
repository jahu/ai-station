"""Frozen prepared runtime/GPU observations retain legacy whole-avatar identities."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from ai_station_runner.sonic_contract import checked_recipe
from ai_station_runner.sonic_jobs import WholeAvatarRequest
from app import whole_avatars as whole
from fastapi import HTTPException
from test_whole_avatars import PROFILE, RECIPE, settings, task
from test_whole_avatars import sources as sources


@pytest.fixture
def managed():
    return {
        **deepcopy(PROFILE),
        "configuration_source": "managed",
        "recipe": {**RECIPE, "environment_id": "b" * 64},
        "eligible_gpu_indices": [7, 11],
    }


def test_legacy_recipe_shape_is_preserved_and_native_agrees():
    assert whole.frozen_recipe(RECIPE) == RECIPE
    assert checked_recipe(RECIPE) == RECIPE
    managed = {**RECIPE, "environment_id": "b" * 64}
    assert whole.frozen_recipe(managed) == checked_recipe(managed) == managed


def test_managed_profile_cannot_advertise_a_legacy_recipe_without_environment():
    with pytest.raises(HTTPException):
        whole.verify_recipe({**PROFILE, "configuration_source": "managed"}, RECIPE)


def test_generation_freezes_same_runtime_gpu_bundle_and_native_identity(session, sources, managed):
    run = whole.create_whole_run(session, settings(sources), task=task(session), observed_profile=managed)
    assert run.parameters["whole_recipe"] == managed["recipe"]
    assert run.parameters["managed_avatar_gpu_indices"] == [7, 11]
    assert run.requested_resources == {"ram_mib": 18432, "gpu_count": 2}
    run.allocated_resources = {"gpus": [7, 11]}
    captured = SimpleNamespace(request=lambda method, path, payload: payload)
    payload = whole.WholeAvatarExecutor()._start(captured, run, None, "unused")
    assert WholeAvatarRequest.model_validate(payload).recipe == managed["recipe"]
    assert payload["gpus"] == [7, 11] and payload["deadline_at"]


@pytest.mark.parametrize("eligible", [[], ["7"], [-1]])
def test_unverified_gpu_observation_cannot_create_generation(session, sources, managed, eligible):
    managed["eligible_gpu_indices"] = eligible
    with pytest.raises(HTTPException) as exc:
        whole.create_whole_run(session, settings(sources), task=task(session), observed_profile=managed)
    assert exc.value.status_code == 409


def test_explicit_gpu_must_fit_and_changed_environment_cannot_resume_old_recipe(session, sources, managed):
    with pytest.raises(HTTPException) as exc:
        whole.create_whole_run(
            session, settings(sources, gpu="9"), task=task(session), observed_profile=managed
        )
    assert exc.value.status_code == 422
    frozen = dict(managed["recipe"])
    managed["recipe"]["environment_id"] = "d" * 64
    with pytest.raises(HTTPException) as exc:
        whole.verify_recipe(managed, frozen)
    assert exc.value.status_code == 409
