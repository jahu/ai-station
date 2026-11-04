"""Device and administrator authority are rechecked between SSE data batches."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from app.api import stream
from app.data_access import DataScope, ScopedSession
from app.data_context import bind_data_scope
from app.db import control_session_factory, get_engine, utcnow
from app.events import append_event
from app.models import Run, User, UserSession
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    ["revoked", "idle_expired", "absolute_expired", "password_rotated", "mfa_enabled", "admin_demoted"],
)
async def test_open_stream_stops_before_new_private_events_when_authority_ends(accounts, reason):
    owner, alice, _ = accounts
    response = alice.post("/api/testing/runs", json={"title": "Synthetic private streaming task"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    inspector = reason == "admin_demoted"
    actor = owner if inspector else alice
    actor_id = actor.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as authority:
        device = authority.scalar(
            select(UserSession).where(UserSession.user_id == actor_id, UserSession.revoked_at.is_(None))
        )
        device_id = device.id
    scope = DataScope(actor_id, inspect_all=inspector, administrator=inspector, session_id=device_id)
    with bind_data_scope(scope), ScopedSession(bind=get_engine(), scope=scope) as data:
        result = stream(UUID(run_id), data, after=0, last_event_id=None)
        iterator = result.body_iterator
        try:
            first = await asyncio.wait_for(anext(iterator), 3)
            assert run_id in first and "run.created" in first
            with control_session_factory()() as authority:
                device = authority.get(UserSession, device_id)
                if reason == "revoked":
                    device.revoked_at = utcnow()
                elif reason == "idle_expired":
                    device.token_record = {
                        **device.token_record,
                        "last_seen_at": (utcnow() - timedelta(hours=1)).isoformat(),
                    }
                elif reason == "absolute_expired":
                    device.token_record = {
                        **device.token_record,
                        "expires_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                    }
                elif reason == "password_rotated":
                    authority.get(User, actor_id).password_changed_at = utcnow()
                elif reason == "mfa_enabled":
                    authority.get(User, actor_id).totp_enabled_at = utcnow()
                else:
                    authority.get(User, actor_id).is_admin = False
                append_event(
                    authority,
                    run_id,
                    "test.private_late",
                    {"text": "Synthetic private event after authority ended"},
                )
                authority.commit()
            frames = []
            for _ in range(3):
                frame = await asyncio.wait_for(anext(iterator), 3)
                frames.append(frame)
                if "event: end" in frame:
                    break
            else:
                raise AssertionError("Revoked authority left the event stream active")
            assert '"authentication_required": true' in frames[-1]
            assert all("Synthetic private event after authority ended" not in frame for frame in frames)
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
        finally:
            await iterator.aclose()
    with control_session_factory()() as authority:
        assert authority.get(Run, run_id).status == "queued"


def test_http_stream_propagates_authenticated_device_to_background_batches(accounts, monkeypatch):
    from app import accounts as account_services

    _, alice, _ = accounts
    response = alice.post("/api/testing/runs", json={"title": "Synthetic HTTP device propagation"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with control_session_factory()() as control:
        run = control.get(Run, run_id)
        run.status = "succeeded"
        owner_id = run.owner_id
        control.commit()
    checked = []
    original = account_services._actor

    def verify(session, principal, **kwargs):
        if kwargs.get("lock"):
            checked.append((principal.user_id, principal.session_id))
        return original(session, principal, **kwargs)

    monkeypatch.setattr(account_services, "_actor", verify)
    result = alice.get("/api/runs/" + run_id + "/stream")
    assert result.status_code == 200 and "event: end" in result.text
    assert len(checked) == 1 and checked[0][0] == owner_id
    with control_session_factory()() as authority:
        assert authority.get(UserSession, checked[0][1]).user_id == owner_id
