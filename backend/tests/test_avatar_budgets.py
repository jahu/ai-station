"""Shared budget through whole-speech avatars; no agent output advertised yet."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.media_jobs import FullAvatarRequest, publish_avatar
from app.models import Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_media_jobs import avatar_sources
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge


@pytest.mark.parametrize("spoken_text", [None, "Dzień dobry."])
def test_full_avatar_shares_one_expiry_through_speech_planner_segments_and_composition(
    full_avatar_bridge, spoken_text
):
    with TestClient(app) as api:
        request = FullAvatarRequest(**avatar_sources(api), speech_text=spoken_text)
        expiry = (utcnow() + timedelta(seconds=30)).isoformat()
        with session_factory()() as session:
            view = publish_avatar(session, request, execution_deadline_at=expiry)
            session.commit()
            tid = view["task_id"]
            for _ in range(10):
                if tick(session, "bounded-avatar") is None:
                    break
            task = session.get(Task, tid)
            rows = list(session.scalars(select(Run).where(Run.task_id == tid)))
            assert rows and all(row.status == "succeeded" for row in rows), [
                (row.capability, row.status, row.error_message) for row in rows
            ]
            assert all(row.parameters["execution_deadline_at"] == expiry for row in rows)
            assert task.metadata_json["media_plan"]["execution_deadline_at"] == expiry
            compose = session.get(Run, task.metadata_json["media_plan"]["compose_run_id"])
            if spoken_text:
                planner = next(row for row in rows if row.executor_type == "avatar_media_plan")
                assert compose.parent_run_id == planner.id
            assert task.metadata_json["media_plan"]["final_artifact_id"]
            before = len(rows)
            replay = publish_avatar(session, request, execution_deadline_at=expiry)
            assert replay["task_id"] == tid
            assert len(list(session.scalars(select(Run).where(Run.task_id == tid)))) == before
        assert len(full_avatar_bridge) == 2
        assert all(body.deadline_at for body in full_avatar_bridge)


def test_expired_avatar_budget_creates_no_work(full_avatar_bridge):
    with TestClient(app) as api:
        request = FullAvatarRequest(**avatar_sources(api))
        with session_factory()() as session:
            with pytest.raises(ValueError, match="expiry"):
                publish_avatar(
                    session,
                    request,
                    execution_deadline_at=(utcnow() - timedelta(seconds=1)).isoformat(),
                )
            assert not list(session.scalars(select(Run)))
        assert not full_avatar_bridge


def test_expired_planner_cannot_publish_a_new_avatar_timeline(full_avatar_bridge):
    with TestClient(app) as api:
        request = FullAvatarRequest(**avatar_sources(api), speech_text="Dzień dobry.")
        with session_factory()() as session:
            view = publish_avatar(
                session, request, execution_deadline_at=(utcnow() + timedelta(seconds=30)).isoformat()
            )
            session.commit()
            tick(session, "speech")
            planner = session.scalar(
                select(Run).where(Run.task_id == view["task_id"], Run.executor_type == "avatar_media_plan")
            )
            planner.parameters = {
                **planner.parameters,
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            session.commit()
            tick(session, "expired-planner")
            session.refresh(planner)
            assert planner.status == "canceled"
            assert not list(session.scalars(select(Run).where(Run.executor_type == "echomimic")))
        assert not full_avatar_bridge
