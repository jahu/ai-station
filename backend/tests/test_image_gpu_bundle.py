"""Auxiliary image devices share the existing durable locks and release policy."""

import pytest
from app.resources import ResourceUnknown, active_locks, release_run_locks, reserve_gpu, reserve_gpu_bundle
from app.runs import create_run, create_task


def image_run(session, gpu="auto"):
    task = create_task(session, title="image", prompt="neutral scene", capability="image.generate")
    return create_run(
        session, task, run_type="image", capability="image.generate", executor_type="fake", requested_gpu=gpu
    )


def test_bundle_reserves_and_releases_both_dynamic_devices(session):
    run = image_run(session, "7")
    assert reserve_gpu_bundle(session, run, [3, 7], 2) == "7"
    assert run.allocated_resources == {"gpu": "7", "gpus": ["7", "3"]}
    assert run.actual_gpu == "7"
    assert active_locks(session) == {"gpu:3", "gpu:7"}
    assert reserve_gpu(session, image_run(session), [3, 7]) is None
    release_run_locks(session, run.id)
    assert active_locks(session) == set()


def test_busy_auxiliary_leaves_no_partial_reservation(session):
    other = image_run(session, "3")
    assert reserve_gpu(session, other, [3, 7]) == "3"
    run = image_run(session, "7")
    assert reserve_gpu_bundle(session, run, [3, 7], 2) is None
    assert active_locks(session) == {"gpu:3"}
    assert run.actual_gpu is None
    assert not run.allocated_resources


def test_primary_selection_is_preserved_and_single_large_device_is_supported(session):
    run = image_run(session, "7")
    assert reserve_gpu_bundle(session, run, [3, 7], 1) == "7"
    assert run.allocated_resources["gpus"] == ["7"]


@pytest.mark.parametrize("gpu,available,count", [("auto", [3], 2), ("9", [3, 7], 2), ("auto", [3, 7], 0)])
def test_invalid_allocations_fail_before_locking(session, gpu, available, count):
    with pytest.raises(ResourceUnknown):
        reserve_gpu_bundle(session, image_run(session, gpu), available, count)
    assert not active_locks(session)
