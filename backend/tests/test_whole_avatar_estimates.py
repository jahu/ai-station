"""Read-only timing projections from actual saved progress events."""

from copy import deepcopy
from datetime import timedelta

import pytest
from app.db import utcnow
from app.events import append_event
from app.models import RunEvent
from app.whole_avatar_jobs import animation_estimate
from sqlalchemy import func, select
from test_whole_avatars import create
from test_whole_avatars import sources as sources


@pytest.fixture
def measured(session, sources, monkeypatch):
    run = create(session, sources)
    run.status = "running"
    now = utcnow()
    progress = {"phase": "animating", "completed_windows": 5, "total_windows": 25}
    run.metadata_json = {"avatar_progress": progress}
    # Model preparation precedes these real diffusion observations and must not
    # inflate the rate. Four measured windows take 68 seconds.
    first = append_event(session, run.id, "avatar.progress", {**progress, "completed_windows": 1})
    first.created_at = now - timedelta(seconds=70)
    last = append_event(session, run.id, "avatar.progress", progress)
    last.created_at = now - timedelta(seconds=2)
    session.flush()
    monkeypatch.setattr("app.whole_avatar_jobs.utcnow", lambda: now)
    return run, first, last, now


def test_estimate_uses_saved_measured_speed_and_never_mutates_the_run(session, measured):
    run, _, _, _ = measured
    before = deepcopy(run.metadata_json)
    count = session.scalar(select(func.count()).select_from(RunEvent))
    assert animation_estimate(session, run) == 340
    session.expire_all()  # API/browser restarts do not reset a client timer.
    assert animation_estimate(session, run) == 340
    assert run.metadata_json == before and not session.dirty
    assert session.scalar(select(func.count()).select_from(RunEvent)) == count


@pytest.mark.parametrize(
    "status", ["queued", "preparing", "cancel_requested", "succeeded", "failed", "interrupted"]
)
def test_inactive_or_nonanimating_work_never_has_a_countdown(session, measured, status):
    run, _, _, _ = measured
    run.status = status
    assert animation_estimate(session, run) is None


@pytest.mark.parametrize(
    "fault",
    [
        "too-few",
        "clock-backwards",
        "stale",
        "future",
        "finishing",
        "unknown-count",
        "different-total",
        "boolean",
        "complete",
    ],
)
def test_insufficient_stale_or_inconsistent_observations_hide_the_estimate(session, measured, fault):
    run, first, last, now = measured
    if fault == "too-few":
        first.payload = {**first.payload, "completed_windows": 3}
    elif fault == "clock-backwards":
        first.created_at = last.created_at + timedelta(seconds=1)
    elif fault == "stale":
        first.created_at -= timedelta(seconds=600)
        last.created_at -= timedelta(seconds=600)
    elif fault == "future":
        last.created_at = now + timedelta(seconds=1)
    elif fault == "finishing":
        run.metadata_json = {"avatar_progress": {**last.payload, "phase": "finishing"}}
    elif fault == "unknown-count":
        run.metadata_json = {"avatar_progress": {**last.payload, "completed_windows": 6}}
    elif fault == "different-total":
        first.payload = {**first.payload, "total_windows": 100}
    elif fault == "boolean":
        first.payload = {**first.payload, "completed_windows": True}
    else:
        last.payload = {**last.payload, "completed_windows": 25}
        run.metadata_json = {"avatar_progress": last.payload}
    session.flush()
    assert animation_estimate(session, run) is None
