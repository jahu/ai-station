"""A real legacy-schema upgrade never replays an old privileged approval."""

from datetime import timedelta

import pytest
from app.db import control_session_factory, migrate, utcnow
from app.models import Run, Setting, User
from app.private_ui_state import KEY
from app.runs import claim_next, transition
from app.state import RunStatus
from sqlalchemy import select
from test_private_ui import operator as operator
from test_private_ui import queue, work


@pytest.mark.parametrize("dispatched", [False, True])
def test_ownership_upgrade_preserves_the_old_private_action_and_never_dispatches_it_again(
    operator, legacy_schema, dispatched
):
    client, calls, _ = operator
    response = queue(client)
    assert response.status_code == 202, response.text
    identity, task_id = response.json()["id"], response.json()["task_id"]
    with control_session_factory()() as session:
        run = claim_next(session, "old-worker")
        assert run.id == identity and run.owner_id is None
        if dispatched:
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        frozen = dict(run.parameters)
        session.commit()
    legacy_schema("0036")
    migrate()
    with control_session_factory()() as session:
        user = session.scalar(select(User))
        run = session.get(Run, identity)
        assert user.legacy_operator and user.enabled and user.is_admin
        assert run.owner_id == user.id and run.task.owner_id == user.id
        assert run.task_id == task_id and run.parameters == frozen
        policy = dict(session.get(Setting, KEY).value)
    assert work() == identity
    assert [call[1] for call in calls] == (
        ["/v1/private-access/inspect", "/v1/private-access/cancel"] if dispatched else []
    )
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        assert run.status == ("canceled" if dispatched else "failed")
        assert run.parameters == frozen and run.task_id == task_id
        assert session.get(Setting, KEY).value == policy
