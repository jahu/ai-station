"""Strict lifecycle activation preserves legacy data without ambient authority."""

import os
import subprocess
import sys
from datetime import timedelta

import pytest
from app import models as m
from app.account_profile import KEY, prepare_profile
from app.accounts import bootstrap_admin
from app.config import clear_settings_cache
from app.data_access import ROOTS, DataAccessError, DataScope, ScopedSession
from app.data_context import bind_data_scope
from app.db import control_session_factory, get_engine, session_factory, utcnow
from app.engine import tick
from app.schedule import scheduler_tick
from sqlalchemy import func, inspect, select


def strict(monkeypatch):
    monkeypatch.setenv("AI_STATION_ACCESS_PROFILE", "accounts")
    clear_settings_cache()


def seed(session):
    task = m.Task(title="Legacy task", prompt="Legacy prompt", metadata_json={"preserve": True})
    conversation = m.Conversation(title="Legacy conversation")
    session.add_all([task, conversation])
    session.flush()
    run = m.Run(task_id=task.id, executor_type="fake", parameters={"immutable": "recipe"})
    session.add(run)
    session.flush()
    rows = [
        task,
        run,
        conversation,
        m.Artifact(artifact_type="text", relative_path="artifacts/synthetic.txt", run_id=run.id),
        m.Project(name="Legacy project", repo_path="/synthetic/repository"),
        m.Agent(name="Legacy agent"),
        m.Approval(run_id=run.id, action="Legacy approval"),
        m.MemoryEntry(scope="global", content="Legacy memory"),
        m.Connector(key="legacy", name="Legacy connector"),
        m.ChatProvider(key="legacy", name="Legacy provider"),
        m.CreativeSession(capability="images", title="Legacy creative workspace"),
    ]
    session.add_all(rows)
    session.add(
        m.Message(conversation_id=conversation.id, role="user", content="Legacy message", run_id=run.id)
    )
    session.commit()
    return rows


def snapshot(row):
    return {
        column.key: getattr(row, column.key)
        for column in inspect(type(row)).column_attrs
        if column.key != "owner_id"
    }


def admin(session):
    user = bootstrap_admin(session, "Owner", "synthetic activation password", local_setup=True)
    session.commit()
    return user.id


def test_sole_pending_owner_adopts_all_legacy_roots_without_changing_content(monkeypatch):
    with control_session_factory()() as session:
        rows = seed(session)
        before = {(type(row), row.id): snapshot(row) for row in rows}
        owner = session.scalar(select(m.User.id))
        strict(monkeypatch)
        receipt = prepare_profile(session)
        session.commit()
        session.expire_all()
        assert receipt["legacy_owner_id"] == owner
        assert set(receipt["adopted"]) == {model.__tablename__ for model in ROOTS}
        assert all(receipt["adopted"].values()) and not any(receipt["unassigned"].values())
        for (model, identity), data in before.items():
            row = session.get(model, identity)
            assert row.owner_id == owner and snapshot(row) == data
        assert session.scalar(select(func.count()).select_from(m.Message)) == 1
        assert session.scalar(select(m.AccountEvent.action)) == "access_profile.accounts"


def test_activation_is_idempotent_and_never_silently_adopts_later_orphans(monkeypatch):
    strict(monkeypatch)
    with control_session_factory()() as session:
        receipt = prepare_profile(session)
        session.commit()
        late = m.Task(title="Unverified late record")
        session.add(late)
        session.commit()
        assert prepare_profile(session) == receipt
        session.commit()
        session.refresh(late)
        assert late.owner_id is None
        assert session.scalar(select(func.count()).select_from(m.AccountEvent)) == 1


def test_ambiguous_legacy_ownership_is_not_guessed_or_published(monkeypatch):
    with control_session_factory()() as session:
        task = m.Task(title="Unassigned record")
        session.add_all([task, m.User(username="Other", normalized_username="other")])
        session.commit()
        identity = task.id
        strict(monkeypatch)
        with pytest.raises(RuntimeError, match="ownership inspection"):
            prepare_profile(session)
        session.rollback()
        assert session.get(m.Task, identity).owner_id is None
        assert session.get(m.Setting, KEY) is None


@pytest.mark.parametrize("activated", [False, True])
def test_activated_or_multiuser_data_refuses_operator_profile(monkeypatch, activated):
    strict(monkeypatch)
    with control_session_factory()() as session:
        if activated:
            prepare_profile(session)
        else:
            session.add(m.User(username="Other", normalized_username="other"))
        session.commit()
        monkeypatch.setenv("AI_STATION_ACCESS_PROFILE", "operator")
        clear_settings_cache()
        with pytest.raises(RuntimeError, match="refusing operator"):
            prepare_profile(session)


def test_mixed_api_worker_configuration_and_scoped_activation_are_denied(monkeypatch):
    with control_session_factory()() as session:
        with pytest.raises(RuntimeError, match="same access profile"):
            prepare_profile(session, accounts_active=True)
        identity = session.scalar(select(m.User.id))
    strict(monkeypatch)
    with ScopedSession(bind=get_engine(), scope=DataScope(identity)) as session:
        with pytest.raises(PermissionError, match="trusted lifecycle"):
            prepare_profile(session)


def test_unbound_and_missing_owner_cannot_open_a_repository_session(monkeypatch):
    captured = session_factory()
    strict(monkeypatch)
    with pytest.raises(DataAccessError, match="explicit owner scope"):
        captured()
    with bind_data_scope(None), session_factory()() as session:
        with pytest.raises(DataAccessError, match="authenticated data owner"):
            session.scalars(select(m.Task)).all()
    with control_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 1


def test_worker_waits_for_first_admin_then_runs_adopted_work(monkeypatch):
    strict(monkeypatch)
    with control_session_factory()() as session:
        rows = seed(session)
        run_id = next(row.id for row in rows if isinstance(row, m.Run))
        prepare_profile(session)
        session.commit()
        assert tick(session, "bootstrap-worker") is None
        assert session.get(m.Run, run_id).status == "queued"
        assert scheduler_tick(session) == []
        admin(session)
        assert tick(session, "bootstrap-worker") == run_id
        session.expire_all()
        assert session.get(m.Run, run_id).status == "succeeded"


@pytest.mark.parametrize("uncertain", ["none", "reservation", "released_reservation", "dispatch", "pid"])
def test_ownerless_work_never_executes_and_uncertain_reservations_are_held(monkeypatch, uncertain):
    strict(monkeypatch)
    with control_session_factory()() as session:
        admin(session)
        prepare_profile(session)
        session.commit()
        task = m.Task(title="Unknown owner")
        session.add(task)
        session.flush()
        run = m.Run(
            task_id=task.id,
            executor_type="never",
            metadata_json={"dispatch_attempted": True} if uncertain == "dispatch" else {},
            pid=123 if uncertain == "pid" else None,
        )
        session.add(run)
        session.flush()
        if uncertain in {"reservation", "released_reservation"}:
            session.add(
                m.ResourceLock(
                    resource_key="gpu:synthetic",
                    run_id=run.id,
                    released_at=utcnow() if uncertain == "released_reservation" else None,
                )
            )
        session.commit()
        identity = run.id

        class Never:
            def execute(self, *_args):
                pytest.fail("An ownerless executor must not run")

        assert tick(session, "strict-worker", executors={"never": Never()}) == identity
        session.expire_all()
        run = session.get(m.Run, identity)
        assert run.status == ("failed" if uncertain in {"none", "released_reservation"} else "interrupted")
        if uncertain not in {"none", "released_reservation"}:
            assert run.metadata_json["cleanup_requires_inspection"]
        if uncertain == "reservation":
            assert (
                session.scalar(
                    select(m.ResourceLock).where(m.ResourceLock.resource_key == "gpu:synthetic")
                ).released_at
                is None
            )


def test_ownerless_schedules_are_not_enqueued(monkeypatch):
    strict(monkeypatch)
    with control_session_factory()() as session:
        admin(session)
        prepare_profile(session)
        session.commit()
        agent = m.Agent(
            name="Unassigned schedule",
            provider="local-openai-compatible",
            trigger="interval",
            interval_seconds=60,
            next_run_at=utcnow() - timedelta(seconds=10),
            enabled=True,
        )
        session.add(agent)
        session.commit()
        assert scheduler_tick(session) == []
        assert session.scalar(select(func.count()).select_from(m.Task)) == 0


def test_accounts_configuration_installs_real_api_and_bootstraps_without_wrapper(tmp_path):
    code = """
from fastapi.testclient import TestClient
from app.api import app
from app.account_profile import KEY
from app.db import control_session_factory
from app.models import Setting,Run
assert app.state.account_access_enabled
with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',50000)) as client:
 assert client.get('/api/auth').json()['setup_required']
 assert client.get('/api/runs').status_code==401
 response=client.post('/api/auth/setup',json={'username':'NewOwner','password':'synthetic profile password'})
 assert response.status_code==201,response.text
 user_id=response.json()['user']['id']
 queued=client.post('/api/testing/runs',json={'title':'Strict profile fixture'})
 assert queued.status_code==202,queued.text
 assert client.get('/api/admin/users').status_code==200
 with control_session_factory()() as session:
  assert session.get(Setting,KEY).value['legacy_owner_id']==user_id
  assert session.get(Run,queued.json()['id']).owner_id==user_id
print('strict configured API passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={
            **os.environ,
            "AI_STATION_ACCESS_PROFILE": "accounts",
            "AI_STATION_DATA_DIR": str(tmp_path / "configured-profile"),
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_BIND_HOST": "127.0.0.1",
            "AI_STATION_LAN_HOST": "",
            "AI_STATION_ACCESS_ORIGINS": "",
        },
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
