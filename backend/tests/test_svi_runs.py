"""Durable SVI intent/Run creation over temporary data, no real model execution."""

from uuid import uuid4

import pytest
from app.models import Run, Task
from app.svi_executor import GEOMETRY, RAM_MIB
from app.svi_runs import create_svi_run
from app.video_schema import VideoRequest
from fastapi import HTTPException
from sqlalchemy import select
from test_svi_executor import owned_pair  # noqa: F401 -- common owned-source fixture


def request(pair, **changes):
    return VideoRequest.model_validate(
        {
            "prompt": "A sailboat turns",
            "image_artifact_id": pair.source.id,
            **{key: value for key, value in GEOMETRY.items() if key != "fps"},
            **changes,
        }
    )


def capabilities(pair):
    return {
        "available": True,
        "backend": "wan22-svi-pro-q4",
        **{key: value for key, value in GEOMETRY.items() if key != "frames"},
        "native_window_frames": 81,
        "continuation_frames": 4,
        "memory_estimate_mib": RAM_MIB,
        "managed_runtime": dict(pair.current.parameters["managed_runtime"]),
        "eligible_gpu_indices": [7],
    }


def test_svi_intent_queues_an_ordinary_owned_run_with_full_resources_and_source_snapshot(session, pair):
    body = request(pair)
    run = create_svi_run(session, body, observed_profile=capabilities(pair))
    assert run.status == "queued" and run.retry_class == "inspect"
    assert run.executor_type == "wan_svi_video" and run.execution_target == "host"
    assert run.requested_gpu == "auto" and run.requested_resources == {"ram_mib": RAM_MIB}
    assert run.effective_permissions == ["filesystem_read", "workspace_write"]
    assert run.parameters["image"] == pair.current.parameters["image"]
    assert run.parameters["parent_artifact_ids"] == [pair.source.id]
    assert run.parameters["fps"] == 15 and run.parameters["frames"] == 81
    assert session.get(Task, run.task_id).prompt == body.prompt
    session.commit()
    session.expire_all()
    assert (
        session.get(Run, run.id).parameters["managed_runtime"] == pair.current.parameters["managed_runtime"]
    )


@pytest.mark.parametrize(
    "change", ["unavailable", "wrong_fps", "missing_engine", "small_memory", "missing_gpu", "wrong_overlap"]
)
def test_unqualified_or_changed_profile_cannot_create_a_task_or_run(session, pair, change):
    profile = capabilities(pair)
    if change == "unavailable":
        profile["available"] = False
    elif change == "wrong_fps":
        profile["fps"] = 24
    elif change == "missing_engine":
        profile["managed_runtime"] = None
    elif change == "small_memory":
        profile["memory_estimate_mib"] = 11264
    elif change == "missing_gpu":
        profile["eligible_gpu_indices"] = []
    else:
        profile["continuation_frames"] = 17
    before = (list(session.scalars(select(Task.id))), list(session.scalars(select(Run.id))))
    with pytest.raises(HTTPException) as error:
        create_svi_run(session, request(pair), observed_profile=profile)
    assert error.value.status_code == 409
    assert before == (list(session.scalars(select(Task.id))), list(session.scalars(select(Run.id))))


@pytest.mark.parametrize(
    "changes",
    [
        {"frames": 49},
        {"width": 512},
        {"steps": 4},
        {"cfg": 7},
        {"gpu": "0"},
        {"image_artifact_id": None},
        {"model_id": str(uuid4())},
    ],
)
def test_incompatible_request_fails_before_enqueue(session, pair, changes):
    before = list(session.scalars(select(Run.id)))
    with pytest.raises(HTTPException):
        create_svi_run(session, request(pair, **changes), observed_profile=capabilities(pair))
    assert list(session.scalars(select(Run.id))) == before


def test_an_existing_task_keeps_its_identity_and_parent_link(session, pair):
    task = session.get(Task, pair.current.task_id)
    run = create_svi_run(
        session, request(pair), task=task, parent_run_id=pair.current.id, observed_profile=capabilities(pair)
    )
    assert run.task_id == task.id and run.parent_run_id == pair.current.id


def test_selected_model_engine_and_eligible_devices_are_frozen(session, pair):
    identity = str(uuid4())
    profile = capabilities(pair)
    profile["video_model"] = {
        "definition_id": identity,
        "name": "SVI Pro",
        "binding": {"managed_runtime": dict(profile["managed_runtime"])},
    }
    run = create_svi_run(session, request(pair, model_id=identity), observed_profile=profile)
    profile["managed_runtime"]["environment_id"] = "d" * 64
    profile["eligible_gpu_indices"].clear()
    profile["video_model"]["binding"]["managed_runtime"]["environment_id"] = "e" * 64
    assert run.parameters["managed_runtime"]["environment_id"] == "b" * 64
    assert run.parameters["managed_video_gpu_indices"] == [7]
    assert run.parameters["video_model"]["binding"]["managed_runtime"]["environment_id"] == "b" * 64
