from app.resources import release_run_locks, reserve_memory
from app.runs import create_run, create_task


def test_memory_admission_retains_other_live_reservations_and_releases_after_exit(session):
    task = create_task(session, title="Media", prompt="", capability="video.long")
    first = create_run(
        session, task, run_type="video", capability="video.generate", executor_type="wan_video"
    )
    second = create_run(
        session, task, run_type="video", capability="video.generate", executor_type="wan_video"
    )
    assert reserve_memory(session, first, 32000, 16000)
    assert not reserve_memory(session, second, 32000, 16000)
    release_run_locks(session, first.id)
    assert reserve_memory(session, second, 32000, 16000)
    assert second.allocated_resources["ram_mib"] == 16000
    assert not reserve_memory(session, first, None, 1000)
