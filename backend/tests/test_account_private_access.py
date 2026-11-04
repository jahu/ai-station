"""Owned private-access operations share machine policy, never private Run history."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.accounts import authenticate_cookies, change_password, update_user
from app.data_access import DataAccessError, data_session_for, data_session_for_run
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Run, Setting
from app.private_ui import PrivateAccessExecutor, finish
from app.private_ui_state import KEY, lock
from app.recovery import recover_stale
from app.runner_client import RunnerClient
from app.runs import claim_next, transition
from app.state import RunStatus
from test_account_private_api import PASSWORD, browser
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app

ORIGIN = "https://ai-station.synthetic.ts.net"


@pytest.fixture
def native(monkeypatch):
    calls = []
    service = {
        "state": "Running",
        "available": True,
        "installed": True,
        "node_online": True,
        "node_id": "synthetic-node",
        "origin": ORIGIN,
        "serving": False,
    }

    def request(_client, method, path, json=None):
        calls.append((method, path, json))
        if path.endswith("/link"):
            return {"url": "https://login.tailscale.com/a/SYNTHETIC-PRIVATE-LINK"}
        if method == "GET":
            return dict(service)
        if path.endswith("/cancel"):
            service["serving"] = False
            return {"phase": "canceled", "process_confirmed_gone": True, "service": dict(service)}
        if json["operation"] == "serve_on":
            service["serving"] = True
        if json["operation"] == "stop":
            service["serving"] = False
        return {"phase": "succeeded", "process_confirmed_gone": True, "service": dict(service)}

    monkeypatch.setattr(RunnerClient, "request", request)
    return calls, service


def enqueue(browser, operation="start", revision=0, **extra):
    return browser.post(
        "/api/private-access",
        json={
            "operation": operation,
            "expected_revision": revision,
            "client_request_id": str(uuid4()),
            **extra,
        },
    )


def work():
    with control_session_factory()() as queue:
        return tick(
            queue, "account-private-access-worker", executors={"private_access": PrivateAccessExecutor()}
        )


def test_fresh_account_administrator_can_observe_private_access_without_operator_password(accounts, native):
    owner, alice, _ = accounts
    status = owner.get("/api/private-access")
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "Running" and status.json()["available"]
    assert alice.get("/api/private-access").status_code == 403


def test_first_account_action_queues_owned_work_and_only_the_worker_dispatches(accounts, native):
    owner, alice, _ = accounts
    queued = enqueue(owner)
    assert queued.status_code == 202, queued.text
    assert native[0] == []
    rid = queued.json()["id"]
    assert alice.get("/api/runs/" + rid).status_code == 404
    assert work() == rid
    assert owner.get("/api/runs/" + rid).json()["status"] == "succeeded"
    assert [call[1] for call in native[0]] == ["/v1/private-access/actions"]
    owner_id = owner.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as queue:
        assert queue.get(Run, rid).owner_id == owner_id


def second_admin(owner, application):
    created = owner.post(
        "/api/admin/users", json={"username": "OtherAdmin", "password": PASSWORD, "is_admin": True}
    )
    assert created.status_code == 201, created.text
    other = browser(application)
    assert (
        other.post("/api/auth/login", json={"username": "OtherAdmin", "password": PASSWORD}).status_code
        == 200
    )
    return other


def principal(browser):
    with control_session_factory()() as auth:
        return authenticate_cookies(auth, dict(browser.cookies))


def test_two_admins_share_only_busy_policy_facts_not_action_ids_or_interactive_links(
    accounts, private_app, native
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    queued = enqueue(owner, "login")
    assert queued.status_code == 202, queued.text
    rid = queued.json()["id"]
    native[1].update(daemon_id=rid, debug_log="Synthetic private daemon log")
    for endpoint in ("/api/runs/" + rid, f"/api/private-access/actions/{rid}/link"):
        assert other.get(endpoint).status_code == 404
    shared = other.get("/api/private-access")
    assert shared.json()["busy"] and shared.json()["run"] is None
    assert rid not in shared.text and "SYNTHETIC-PRIVATE-LINK" not in shared.text
    assert "Synthetic private daemon log" not in shared.text
    conflict = enqueue(other, revision=1)
    assert conflict.status_code == 409 and rid not in conflict.text
    assert work() == rid
    link = owner.get(f"/api/private-access/actions/{rid}/link")
    assert link.status_code == 200 and link.headers["cache-control"] == "no-store"
    shared = other.get("/api/private-access")
    assert not shared.json()["busy"] and shared.json()["run"] is None
    assert rid not in shared.text
    own = enqueue(other, revision=1)
    assert own.status_code == 202, own.text
    assert owner.get("/api/runs/" + own.json()["id"]).status_code == 404
    assert work() == own.json()["id"]


def test_receipt_replay_and_conflicting_scope_preserve_one_private_task(accounts, native):
    owner, _, _ = accounts
    body = {"operation": "login", "expected_revision": 0, "client_request_id": str(uuid4())}
    first = owner.post("/api/private-access", json=body)
    assert first.status_code == 202, first.text
    assert owner.post("/api/private-access", json=body).json()["id"] == first.json()["id"]
    assert owner.post("/api/private-access", json={**body, "operation": "start"}).status_code == 409
    assert native[0] == []


def test_account_password_change_invalidates_queued_authority_without_native_dispatch(accounts, native):
    owner, _, _ = accounts
    queued = enqueue(owner)
    assert queued.status_code == 202, queued.text
    changed = owner.post(
        "/api/account/password", json={"password": PASSWORD, "new_password": PASSWORD + " new"}
    )
    assert changed.status_code == 200
    assert work() == queued.json()["id"]
    assert native[0] == []
    with control_session_factory()() as queue:
        assert queue.get(Run, queued.json()["id"]).status == "failed"


def test_device_logout_does_not_invalidate_approved_durable_work(accounts, native):
    owner, _, _ = accounts
    queued = enqueue(owner)
    assert queued.status_code == 202, queued.text
    assert owner.post("/api/auth/logout").status_code == 200
    assert work() == queued.json()["id"]
    with control_session_factory()() as queue:
        assert queue.get(Run, queued.json()["id"]).status == "succeeded"


@pytest.mark.parametrize("reason", ["password", "role", "disabled"])
def test_authority_change_after_dispatch_cancels_only_the_owned_action_before_publication(
    accounts, private_app, native, monkeypatch, reason
):
    owner, _, _ = accounts
    actor = principal(owner)
    other_actor = principal(second_admin(owner, private_app)) if reason != "password" else None
    queued = enqueue(owner, "enable", node_id="synthetic-node", origin=ORIGIN)
    assert queued.status_code == 202, queued.text
    original = RunnerClient.request

    def revoke(client, method, path, json=None):
        result = original(client, method, path, json)
        if path.endswith("/actions"):
            with control_session_factory()() as auth:
                if reason == "password":
                    change_password(auth, actor, PASSWORD, PASSWORD + " replaced")
                else:
                    update_user(
                        auth,
                        other_actor,
                        actor.user_id,
                        enabled=reason != "disabled",
                        is_admin=reason != "role",
                    )
                auth.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", revoke)
    assert work() == queued.json()["id"]
    assert [call[1] for call in native[0]] == ["/v1/private-access/actions", "/v1/private-access/cancel"]
    assert all(call[2]["run_id"] == queued.json()["id"] for call in native[0])
    with control_session_factory()() as queue:
        assert queue.get(Run, queued.json()["id"]).status == "canceled"
        assert not queue.get(Setting, KEY).value["enabled"]


def test_new_authenticator_invalidates_a_previously_approved_private_action(accounts, native):
    import pyotp
    from app.account_mfa import begin_enrollment, confirm_enrollment

    owner, _, _ = accounts
    actor = principal(owner)
    queued = enqueue(owner)
    assert queued.status_code == 202, queued.text
    with control_session_factory()() as auth:
        enrollment = begin_enrollment(auth, actor, PASSWORD)
        confirm_enrollment(auth, actor, PASSWORD, pyotp.TOTP(enrollment.secret).now())
        auth.commit()
    assert work() == queued.json()["id"]
    assert native[0] == []
    with control_session_factory()() as queue:
        assert queue.get(Run, queued.json()["id"]).status == "failed"


def test_failed_publication_shares_only_inspection_fact_and_another_admin_can_disable(
    accounts, private_app, native
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    queued = enqueue(owner, "enable", node_id="synthetic-node", origin=ORIGIN)
    assert queued.status_code == 202, queued.text
    native[1]["node_id"] = "unexpected-device"
    assert work() == queued.json()["id"]
    assert owner.get("/api/runs/" + queued.json()["id"]).json()["status"] == "interrupted"
    shared = other.get("/api/private-access")
    assert shared.json()["run"] is None and shared.json()["needs_inspection"]
    assert not shared.json()["enabled"] and queued.json()["id"] not in shared.text
    assert enqueue(other, revision=1).status_code == 409
    cleanup = enqueue(other, "disable", revision=1)
    assert cleanup.status_code == 202, cleanup.text
    assert work() == cleanup.json()["id"]
    assert other.get("/api/runs/" + cleanup.json()["id"]).json()["status"] == "succeeded"
    assert owner.get("/api/runs/" + cleanup.json()["id"]).status_code == 404
    with control_session_factory()() as queue:
        assert queue.get(Run, queued.json()["id"]).status == "interrupted"
        assert not queue.get(Setting, KEY).value["enabled"]


def test_consent_required_retains_an_existing_origin_without_publishing_a_replacement(
    accounts, native, monkeypatch
):
    owner, _, _ = accounts
    first = enqueue(owner, "enable", node_id="synthetic-node", origin=ORIGIN)
    assert first.status_code == 202 and work() == first.json()["id"]
    replacement = "https://replacement.synthetic.ts.net"
    queued = enqueue(owner, "enable", revision=1, node_id="replacement-node", origin=replacement)
    assert queued.status_code == 202, queued.text
    original = RunnerClient.request

    def consent(client, method, path, json=None):
        result = original(client, method, path, json)
        if path.endswith("/actions"):
            result["phase"] = "https_consent_required"
        return result

    monkeypatch.setattr(RunnerClient, "request", consent)
    assert work() == queued.json()["id"]
    result = owner.get("/api/runs/" + queued.json()["id"])
    assert result.json()["status"] == "succeeded"
    assert result.json()["metadata"]["private_access_outcome"] == "https_consent_required"
    with control_session_factory()() as queue:
        assert queue.get(Setting, KEY).value["origin"] == ORIGIN
        assert queue.get(Setting, KEY).value["revision"] == 2


def test_stale_dispatched_account_operation_is_inspected_without_replay(accounts, native):
    owner, _, _ = accounts
    queued = enqueue(owner)
    assert queued.status_code == 202, queued.text
    rid = queued.json()["id"]
    with control_session_factory()() as queue:
        run = claim_next(queue, "vanished-private-worker")
        assert run.id == rid
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        queue.commit()
        assert rid in recover_stale(queue)
        queue.commit()
    assert work() == rid
    assert [call[1] for call in native[0]] == ["/v1/private-access/inspect"]
    assert owner.get("/api/runs/" + rid).json()["status"] == "succeeded"


def test_cancel_before_dispatch_and_cross_account_inspection_cannot_start_tools(accounts, native):
    owner, alice, _ = accounts
    queued = enqueue(owner, "login")
    assert queued.status_code == 202, queued.text
    rid = queued.json()["id"]
    assert alice.post("/api/runs/" + rid + "/cancel").status_code == 404
    assert (
        owner.get(
            f"/api/private-access/actions/{rid}/link", headers={"X-AI-Station-Inspect-All": "true"}
        ).status_code
        == 403
    )
    assert owner.post("/api/runs/" + rid + "/cancel").status_code == 200
    work()
    assert native[0] == []
    assert owner.get("/api/runs/" + rid).json()["status"] == "canceled"


def test_policy_write_is_atomic_with_owner_transaction_and_general_sql_stays_denied(accounts, native):
    from sqlalchemy import update

    owner, _, _ = accounts
    queued = enqueue(owner, "enable", node_id="synthetic-node", origin=ORIGIN)
    assert queued.status_code == 202, queued.text
    actor = principal(owner)
    with data_session_for(actor) as session:
        with pytest.raises(DataAccessError):
            session.execute(update(Setting).where(Setting.key == KEY).values(value={}))
        policy = lock(session)
        with pytest.raises(ValueError, match="approved operation stage"):
            policy.value = {**policy.value, "enabled": True, "origin": ORIGIN, "node_id": "synthetic-node"}
    with control_session_factory()() as queue:
        assert queue.get(Setting, KEY).value["enabled"] is False
        assert queue.get(Run, queued.json()["id"]).status == "queued"
    with data_session_for(actor, inspect_all=True) as session, pytest.raises(DataAccessError):
        lock(session)
    with data_session_for_run(queued.json()["id"], actor.user_id) as session, pytest.raises(DataAccessError):
        lock(session)  # Execution cannot borrow a generic machine-policy grant.
    with control_session_factory()() as queue:
        run = claim_next(queue, "atomic-private-access-worker")
        transition(queue, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(queue, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        queue.commit()
    with data_session_for_run(queued.json()["id"], actor.user_id) as session:
        finish(
            session,
            session.get(Run, queued.json()["id"]),
            {
                "phase": "succeeded",
                "process_confirmed_gone": True,
                "service": {"serving": True, "origin": ORIGIN, "node_id": "synthetic-node"},
            },
        )
        session.rollback()
    with control_session_factory()() as queue:
        assert queue.get(Setting, KEY).value["enabled"] is False
        assert queue.get(Run, queued.json()["id"]).status == "running"
