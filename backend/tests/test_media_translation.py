import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.executors import EXECUTORS
from app.media_translation import RECEIPT, validate_media_translation
from app.media_translation_text import digest
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import request_cancel, transition
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_llama import managed as managed


def settings(client, **values):
    current = client.get("/api/generation/preferences").json()
    response = client.put(
        "/api/generation/preferences",
        json={**current, "model": "local-translator", "enabled": True, **values},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, **values):
    response = client.post(
        "/api/images/runs",
        json={"mode": "t2i", "backend": "juggernaut", "prompt": "czerwony rower", "seed": 42, **values},
    )
    assert response.status_code == 202, response.text
    return response.json()


def work():
    with session_factory()() as session:
        return tick(session, "translation-test")


def read(client, identifier):
    return client.get("/api/runs/" + identifier).json()


@pytest.fixture
def fake(monkeypatch):
    calls, outputs = [], []

    async def complete(session, params):
        calls.append(params)
        assert params["provider"] == "local-openai-compatible"
        assert params["location"] == "local" and params["require_complete"]
        assert "tools" not in params and "reasoning" not in params
        values = json.loads(params["messages"][-1]["content"])
        yield json.dumps(
            {
                key: text.replace("czerwony rower", "a red bicycle").replace("bez rozmycia", "without blur")
                for key, text in values.items()
            }
        )

    monkeypatch.setattr("app.media_translation.completion_stream", complete)

    class FakeMedia:
        def execute(self, session, run):
            assert run.status == "claimed"
            validate_media_translation(session, run)
            outputs.append(dict(run.parameters))
            for status in ["preparing", "running", "succeeded"]:
                transition(session, run, status, event_type="fake." + status)
            return "done"

    monkeypatch.setitem(EXECUTORS, "photo_pipe", FakeMedia())
    monkeypatch.setattr(
        RunnerClient, "inspect_process", lambda *_: (_ for _ in ()).throw(RunnerError(404, "No process"))
    )
    return calls, outputs


def test_default_off_and_explicit_override_have_no_extra_work(fake):
    calls, outputs = fake
    with TestClient(app) as client:
        assert client.get("/api/generation/preferences").json()["enabled"] is False
        first = submit(client)
        assert RECEIPT not in first["metadata"] and "translation" not in first["parameters"]
        work()
        settings(client)
        second = submit(client, translation={"mode": "off"})
        assert RECEIPT not in second["metadata"]
        work()
        assert calls == [] and len(outputs) == 2


def test_worker_translates_before_media_and_keeps_immutable_parameters(fake):
    calls, outputs = fake
    with TestClient(app) as client:
        settings(client)
        media = submit(client, negative="bez rozmycia", width=768, height=1024)
        prep = media["metadata"][RECEIPT]["preparation_run_id"]
        assert media["parameters"]["prompt"] == "czerwony rower"
        assert calls == outputs == []
        assert work() == prep
        assert outputs == []
        prepared = read(client, media["id"])
        assert prepared["parameters"]["prompt"] == "a red bicycle"
        assert prepared["parameters"]["negative"] == "without blur"
        assert prepared["parameters"]["seed"] == 42
        assert (prepared["parameters"]["width"], prepared["parameters"]["height"]) == (768, 1024)
        assert prepared["metadata"][RECEIPT]["original"]["prompt"] == "czerwony rower"
        assert read(client, prep)["status"] == "succeeded"
        assert work() == media["id"]
        assert len(outputs) == len(calls) == 1
        artifact = prepared["metadata"][RECEIPT]["artifact_id"]
        receipt = client.get(f"/api/artifacts/{artifact}/file").json()
        assert receipt["original"]["prompt"] == "czerwony rower"
        assert receipt["effective"]["prompt"] == "a red bicycle"
    with session_factory()() as session:
        assert active_locks(session) == set()


def test_settings_are_revisioned_and_snapshotted_on_enqueue(fake):
    with TestClient(app) as client:
        chosen = settings(client)
        media = submit(client)
        settings(client, enabled=False, model="another-local-translator")
        stale = client.put("/api/generation/preferences", json=chosen)
        assert stale.status_code == 409
        work()
        prep = read(client, media["metadata"][RECEIPT]["preparation_run_id"])
        assert prep["parameters"]["model"] == "local-translator"
        assert prep["parameters"]["policy"]["revision"] == chosen["revision"]


def test_failure_blocks_media_and_user_can_retry_the_prompt_or_use_original(fake, monkeypatch):
    async def fail(*_):
        raise ValueError("translator unavailable")
        yield

    monkeypatch.setattr("app.media_translation.completion_stream", fail)
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        work()
        work()
        assert read(client, media["id"])["status"] == "failed"
        assert fake[1] == []
        assert client.post(f"/api/images/runs/{media['id']}/retry").status_code == 409
        body = {"translation": "original", "client_request_id": str(uuid4())}
        retry = client.post(f"/api/images/runs/{media['id']}/retry", json=body)
        assert retry.status_code == 202, retry.text
        assert retry.json()["parameters"]["prompt"] == "czerwony rower"
        assert retry.json()["metadata"][RECEIPT]["status"] == "original"
        again = client.post(f"/api/images/runs/{media['id']}/retry", json=body)
        assert again.json()["id"] == retry.json()["id"]
        work()
        assert fake[1][0]["prompt"] == "czerwony rower"


def test_retranslation_reuses_frozen_policy_even_after_default_changes(fake, monkeypatch):
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        prep = media["metadata"][RECEIPT]["preparation_run_id"]
        client.post(f"/api/runs/{prep}/cancel")
        work()
        settings(client, enabled=False, model="new-default")
        retry = client.post(f"/api/images/runs/{media['id']}/retry", json={"translation": "retry"})
        assert retry.status_code == 202, retry.text
        retry_prep = retry.json()["metadata"][RECEIPT]["preparation_run_id"]
        assert read(client, retry_prep)["parameters"]["model"] == "local-translator"
        work()
        work()
        assert read(client, retry.json()["id"])["status"] == "succeeded"


def test_review_is_a_dependency_and_edits_bind_the_approved_payload(fake):
    with TestClient(app) as client:
        settings(client)
        media = submit(client, translation={"review": True})
        work()
        waiting = read(client, media["id"])
        receipt = waiting["metadata"][RECEIPT]
        assert receipt["status"] == "waiting_for_review"
        assert waiting["parameters"]["prompt"] == "czerwony rower"
        assert work() is None
        review = read(client, receipt["review_run_id"])
        assert review["status"] == "waiting_for_approval"
        body = {
            "expected_hash": digest(review["parameters"]["effective"]),
            "effective": {"prompt": "A red bicycle at sunset"},
        }
        approved = client.post(f"/api/generation/translations/{review['id']}/review", json=body)
        assert approved.status_code == 200, approved.text
        assert (
            client.post(f"/api/generation/translations/{review['id']}/review", json=body).status_code == 409
        )
        work()
        work()
        assert fake[1][0]["prompt"] == "A red bicycle at sunset"
        assert len(fake[0]) == 1, "Review must not reload/retranslate with an LLM"


def test_media_stop_cancels_queued_translation_and_parked_review(fake):
    with TestClient(app) as client:
        settings(client)
        first = submit(client)
        client.post(f"/api/runs/{first['id']}/cancel")
        assert read(client, first["metadata"][RECEIPT]["preparation_run_id"])["status"] == "canceled"
        assert work() is None
        second = submit(client, translation={"review": True})
        work()
        receipt = read(client, second["id"])["metadata"][RECEIPT]
        client.post(f"/api/runs/{second['id']}/cancel")
        assert read(client, receipt["review_run_id"])["status"] == "canceled"
        assert work() is None and fake[1] == []


def test_stop_during_inference_closes_stream_and_publishes_no_prompt(fake, monkeypatch):
    closed = []

    async def stream(session, params):
        try:
            run = session.scalar(select(Run).where(Run.executor_type == "media_translate"))
            parent = session.get(Run, run.parameters["consumer_run_id"])
            request_cancel(session, parent)
            session.commit()
            yield '{"prompt":"should never be adopted"}'
        finally:
            assert session.get(Run, run.id).status == "cancel_requested"
            closed.append(True)

    monkeypatch.setattr("app.media_translation.completion_stream", stream)
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        work()
        assert read(client, media["id"])["parameters"]["prompt"] == "czerwony rower"
        assert read(client, media["metadata"][RECEIPT]["preparation_run_id"])["status"] == "canceled"
        assert closed == [True] and fake[1] == []


def test_changed_receipt_cannot_dispatch_media(fake):
    from app.config import get_settings
    from app.models import Artifact

    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        work()
        prepared = read(client, media["id"])
        with session_factory()() as session:
            artifact = session.get(Artifact, prepared["metadata"][RECEIPT]["artifact_id"])
            (get_settings().data_dir / artifact.relative_path).write_text('{"prompt":"tampered"}')
        work()
        assert read(client, media["id"])["status"] == "failed" and fake[1] == []


def test_retry_reuses_effective_prompt_without_a_second_inference(fake):
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        work()
        client.post(f"/api/runs/{media['id']}/cancel")
        retry = client.post(f"/api/images/runs/{media['id']}/retry")
        assert retry.status_code == 202, retry.text
        work()
        assert len(fake[0]) == 1 and fake[1][0]["prompt"] == "a red bicycle"


@pytest.mark.parametrize("mode,count", [("img2img", 1), ("recompose", 2)])
def test_edit_and_multiple_reference_order_are_preserved(fake, mode, count):
    from test_images import png

    with TestClient(app) as client:
        settings(client)
        ids = [
            client.post(
                "/api/images/uploads", files={"file": (f"source-{n}.png", png(), "image/png")}
            ).json()["id"]
            for n in range(count)
        ]
        media = submit(
            client, mode=mode, backend="qwen", seed=None, edit_prompt="czerwony rower", input_artifact_ids=ids
        )
        work()
        prepared = read(client, media["id"])
        assert prepared["parameters"]["inputs"] == media["parameters"]["inputs"]
        assert prepared["parameters"]["parent_artifact_ids"] == ids
        assert prepared["parameters"]["edit_prompt" if mode == "img2img" else "prompt"] == "a red bicycle"
        work()
        assert fake[1][0]["parent_artifact_ids"] == ids


def test_source_change_is_rejected_before_translation(fake):
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        with session_factory()() as session:
            run = session.get(Run, media["id"])
            run.parameters = {**run.parameters, "inputs": ["artifacts/different.png"]}
            session.commit()
        work()
        assert read(client, media["metadata"][RECEIPT]["preparation_run_id"])["status"] == "failed"
        assert fake[0] == fake[1] == []


def test_stale_translation_is_interrupted_and_never_replayed(fake):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale

    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        prep_id = media["metadata"][RECEIPT]["preparation_run_id"]
        with session_factory()() as session:
            run = session.get(Run, prep_id)
            run.status = "running"
            run.lease_expires_at = utcnow() - timedelta(minutes=1)
            session.commit()
            assert prep_id in recover_stale(session)
            session.commit()
        assert read(client, prep_id)["status"] == "interrupted"
        work()
        assert read(client, media["id"])["status"] == "failed"
        assert fake[0] == fake[1] == []


def test_explicit_enable_requires_model_and_cannot_add_endpoint_or_external_permission(fake):
    with TestClient(app) as client:
        enabled = client.put("/api/generation/preferences", json={"revision": 0, "enabled": True})
        assert enabled.status_code == 409
        assert client.get("/api/generation/preferences").json()["revision"] == 0
        assert (
            client.put(
                "/api/generation/preferences",
                json={"revision": 0, "enabled": True, "model": "local", "endpoint": "https://example.com"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/images/runs", json={"prompt": "rower", "translation": {"external_ai": True}}
            ).status_code
            == 422
        )


def test_missing_permission_and_an_unrelated_preparation_cannot_be_used(fake):
    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        prep_id = media["metadata"][RECEIPT]["preparation_run_id"]
        with session_factory()() as session:
            prep = session.get(Run, prep_id)
            prep.effective_permissions = []
            session.commit()
        work()
        assert read(client, prep_id)["status"] == "failed"
        assert fake[0] == []
        second = submit(client)
        third = submit(client)
        with session_factory()() as session:
            altered = session.get(Run, second["id"])
            altered.metadata_json = {
                **altered.metadata_json,
                RECEIPT: {
                    **altered.metadata_json[RECEIPT],
                    "preparation_run_id": third["metadata"][RECEIPT]["preparation_run_id"],
                },
            }
            session.commit()
        client.post(f"/api/runs/{second['id']}/cancel")
        assert read(client, third["metadata"][RECEIPT]["preparation_run_id"])["status"] == "queued"


def test_trashed_translation_can_be_replaced_without_reusing_its_receipt(fake):
    from app.db import utcnow
    from app.models import Artifact

    with TestClient(app) as client:
        settings(client)
        media = submit(client)
        work()
        client.post(f"/api/runs/{media['id']}/cancel")
        prepared = read(client, media["id"])
        artifact_id = prepared["metadata"][RECEIPT]["artifact_id"]
        with session_factory()() as session:
            session.get(Artifact, artifact_id).trashed_at = utcnow()
            session.commit()
        assert client.post(f"/api/images/runs/{media['id']}/retry").status_code == 409
        retry = client.post(f"/api/images/runs/{media['id']}/retry", json={"translation": "original"})
        assert retry.status_code == 202, retry.text
        assert "artifact_id" not in retry.json()["metadata"][RECEIPT]
        work()
        assert fake[1][0]["prompt"] == "czerwony rower"


def test_cancel_preserves_shared_translation_startup_until_last_consumer_stops(fake, managed):
    model_id, records = managed
    with TestClient(app) as client:
        settings(client, model="llamacpp:" + model_id)
        first, second = submit(client), submit(client)
        with session_factory()() as session:
            loads = session.scalars(select(Run).where(Run.executor_type == "llama_load")).all()
            assert len(loads) == 1
            load_id = loads[0].id
        client.post(f"/api/runs/{first['id']}/cancel")
        assert read(client, load_id)["status"] == "queued"
        client.post(f"/api/runs/{second['id']}/cancel")
        assert read(client, load_id)["status"] == "canceled"
        assert records == {} and work() is None


def test_cancel_does_not_cancel_an_independent_operator_startup(fake, managed):
    from test_llama import load

    model_id, records = managed
    with TestClient(app) as client:
        own = load(client, model_id)
        settings(client, model="llamacpp:" + model_id)
        media = submit(client)
        client.post(f"/api/runs/{media['id']}/cancel")
        assert read(client, own["id"])["status"] == "queued"
        assert records == {}


def test_task_stop_cancels_preparation_and_parked_review(fake):
    from app.task_control import cancel_task

    with TestClient(app) as client:
        settings(client)
        media = submit(client, translation={"review": True})
        work()
        with session_factory()() as session:
            cancel_task(session, session.get(Run, media["id"]).task)
            session.commit()
            assert all(run.status in {"succeeded", "canceled"} for run in session.scalars(select(Run)))
        assert work() is None and fake[1] == []
