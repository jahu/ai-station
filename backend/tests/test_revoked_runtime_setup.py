"""Revoked runtime setup is cleaned in trusted worker coordination, never executed."""

import pytest
from app.db import control_session_factory
from app.models import Artifact, ResourceLock, Run, User
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_runtime_setup_api import body
from test_runtime_setup_api import runtime_catalog as runtime_catalog
from test_runtime_setup_job import bridge as bridge
from test_runtime_setup_job import dispatched, work


@pytest.mark.parametrize("field", ["enabled", "is_admin"])
def test_revoked_owner_can_only_cancel_its_existing_native_preparation(
    accounts, runtime_catalog, bridge, field
):
    owner, _, _ = accounts
    identity = dispatched(owner, runtime_catalog, bridge)
    with control_session_factory()() as db:
        user = db.get(User, db.get(Run, identity).owner_id)
        setattr(user, field, False)
        db.commit()
    assert work() == identity
    assert bridge["cancels"] and bridge["cancels"][0][0] == identity
    assert len(bridge["requests"]) == 1
    with control_session_factory()() as db:
        run = db.get(Run, identity)
        assert run.status == "canceled"
        assert run.metadata_json["process_confirmed_gone"]
        assert all(row.released_at for row in db.scalars(select(ResourceLock)))
        assert not list(db.scalars(select(Artifact)))


def test_unreachable_runner_keeps_revoked_cleanup_pending_and_reserved(accounts, runtime_catalog, bridge):
    owner, _, _ = accounts
    identity = dispatched(owner, runtime_catalog, bridge)
    with control_session_factory()() as db:
        db.get(User, db.get(Run, identity).owner_id).enabled = False
        db.commit()
    bridge["offline"] = True
    assert work() == identity
    with control_session_factory()() as db:
        run = db.get(Run, identity)
        assert run.status == "cancel_requested"
        assert run.metadata_json["cleanup_requires_inspection"]
        assert any(row.released_at is None for row in db.scalars(select(ResourceLock)))
    bridge["offline"] = False
    # Expire the cleanup lease; the next claim confirms Stop without execution.
    from datetime import timedelta

    from app.db import utcnow

    with control_session_factory()() as db:
        db.get(Run, identity).lease_expires_at = utcnow() - timedelta(seconds=2)
        db.commit()
    assert work() == identity
    with control_session_factory()() as db:
        assert db.get(Run, identity).status == "canceled"
    assert len(bridge["requests"]) == 1


@pytest.mark.parametrize("still_running", [False, True])
def test_demotion_during_transfer_prevents_publication_and_runs_only_native_cleanup(
    accounts, runtime_catalog, bridge, still_running
):
    owner, _, _ = accounts
    bridge["keep_running"] = still_running

    def demote(identity):
        with control_session_factory()() as db:
            db.get(User, db.get(Run, identity).owner_id).is_admin = False
            db.commit()

    bridge["callback"] = demote
    created = owner.post("/api/setup/runtimes", json=body(runtime_catalog))
    assert created.status_code == 202, created.text
    identity = created.json()["run"]["id"]
    assert work() == identity
    with control_session_factory()() as db:
        assert db.get(Run, identity).status == "canceled"
        assert not list(db.scalars(select(Artifact)))
    assert bool(bridge["cancels"]) == still_running
    assert len(bridge["requests"]) == 1
