"""The offline child enforces its operation, recipe, scope and durable Stop."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ai_station_runner import runtime_install
from ai_station_runner import svi_environment_job as job


@pytest.fixture
def operation(tmp_path, monkeypatch):
    identity = str(uuid4())
    folder = tmp_path / "runtime/setup" / identity
    folder.mkdir(parents=True)
    request = folder / "svi-request.json"
    body = {
        "run_id": identity,
        "data_root": str(tmp_path),
        "profile": job.svi_environment.PROFILE,
        "manifest_sha256": job.svi_environment.fingerprint(job.svi_environment.recipe()),
        "deadline_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    request.write_text(json.dumps(body))
    request.chmod(0o600)
    runtime_install.atomic_json(folder, "svi.json", {"cancellation_requested": False})
    monkeypatch.setattr(job.sys, "argv", ["fixed-child", str(request)])
    calls = []
    monkeypatch.setattr(job, "require_scope", lambda *values: calls.append(values))
    return request, body, calls


def test_child_observes_stop_during_assembly_before_readiness(operation, monkeypatch):
    path, body, calls = operation

    def prepare(root, identity, *, check, progress):
        assert root == path.parents[3] and identity == body["run_id"]
        check()
        runtime_install.atomic_json(path.parent, "svi.json", {"cancellation_requested": True})
        check()
        pytest.fail("Stopped preparation continued")

    monkeypatch.setattr(job.svi_environment, "prepare", prepare)
    with pytest.raises(InterruptedError):
        job.main()
    assert calls == [(body["run_id"], 4096)]


@pytest.mark.parametrize("failure", ["path", "recipe", "naive_deadline", "expired", "missing_journal"])
def test_child_refuses_invalid_operation_before_assembly(operation, monkeypatch, failure):
    path, body, _ = operation
    if failure == "path":
        path = path.with_name("foreign-request.json")
    elif failure == "recipe":
        body["manifest_sha256"] = "0" * 64
    elif failure == "naive_deadline":
        body["deadline_at"] = datetime.now().isoformat()
    elif failure == "expired":
        body["deadline_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    else:
        path.with_name("svi.json").unlink()
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    monkeypatch.setattr(job.sys, "argv", ["fixed-child", str(path)])
    monkeypatch.setattr(
        job.svi_environment, "prepare", lambda *a, **kw: pytest.fail("Invalid operation assembled")
    )
    with pytest.raises((ValueError, InterruptedError, TimeoutError)):
        job.main()
