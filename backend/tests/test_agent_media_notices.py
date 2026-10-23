import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Notice, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, drain, start
from test_agent_media import implemented_media as implemented_media
from test_music import music_bridge as music_bridge


@pytest.mark.parametrize("caption,expected", [("Piano", "succeeded"), ("fail", "failed")])
def test_media_notifications_wait_for_the_actual_result(implemented_media, music_bridge, caption, expected):
    with TestClient(app) as api:
        agent = create(
            api,
            request={"caption": caption, "duration_seconds": 10},
            notification_policy={"on_success": True, "on_failure": True},
        )
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "notice-root")
            tick(session, "notice-preparation")
            assert not list(session.scalars(select(Notice)))
            drain(session)
            notices = list(session.scalars(select(Notice)))
            assert len(notices) == 1 and notices[0].kind == expected
            media = session.get(Run, notices[0].run_id)
            assert media.capability == "audio.music" and media.task_id == root["task_id"]
            if expected == "succeeded":
                assert notices[0].title == "Agent media ready"
