import pytest
from app import station_update_install as module
from app.db import control_session_factory
from app.engine import tick
from app.models import Run, Setting, User
from app.runs import claim_next
from app.station_update_gate import KEY, take
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_station_update_install import TARGET, installed
from test_station_update_install import offer as offer


@pytest.mark.parametrize(
    "phase,disabled,other_inspector",
    [
        ("succeeded", False, False),
        ("succeeded", True, False),
        ("inspection_required", False, False),
        ("succeeded", False, True),
    ],
)
def test_only_proven_native_completion_reconciles_an_interrupted_update_without_execution(
    accounts, offer, monkeypatch, phase, disabled, other_inspector
):
    identity, native = installed(accounts, offer, monkeypatch)
    with control_session_factory()() as session:
        row = claim_next(session, "old-updater")
        assert row.id == identity
        row.status = "running"
        row.metadata_json = {
            **row.metadata_json,
            "dispatch_attempted": True,
            "native_update": {"target": TARGET},
        }
        claim = row.worker_id, row.claimed_at
        session.commit()
    take(identity, claim)
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        row.status = "interrupted"
        if disabled:
            session.scalar(select(User).where(User.id != row.owner_id)).is_admin = True
            session.get(User, row.owner_id).enabled = False
        session.commit()
    calls = []

    class Proof:
        def station_update(self, value):
            calls.append(value["action"])
            reply = {"run_id": identity, "request": native.parameters, "phase": phase, "target": TARGET}
            if other_inspector and len(calls) == 1:
                # The first IPC wait exceeds its inspection interval. A second
                # worker finishes the same operation before the first returns.
                with control_session_factory()() as second:
                    row = second.get(Run, identity)
                    row.metadata_json = {**row.metadata_json, "native_update_inspect_after": 0}
                    second.commit()
                    module.recover_gate(second, self, "second-inspector")
            return reply

    monkeypatch.setattr(module, "__version__", "0.5.0")
    with control_session_factory()() as session:
        tick(session, "result-inspector", runner=Proof())
        session.expire_all()
        row = session.get(Run, identity)
        assert row.status == ("succeeded" if phase == "succeeded" else "interrupted")
        assert (session.get(Setting, KEY) is None) == (phase == "succeeded")
        if phase == "succeeded":
            assert row.worker_id == ("second-inspector" if other_inspector else "result-inspector")
            assert row.metadata_json["native_result_original_claim"]["worker_id"] == "old-updater"
    assert calls == ["inspect"] * (2 if other_inspector else 1) and not native.calls
