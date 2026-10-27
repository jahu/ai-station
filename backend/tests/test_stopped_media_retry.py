"""An explicit retry has its own Stop boundary and visible conversation turn."""

# Imported fixture names are their pytest injection names.
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.media_retry_intent import FRESH, SOURCE
from app.models import Conversation, Message, Run, Task
from app.runs import create_run
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_media_translation import fake, read, settings, submit, work  # noqa: F401


def stopped_media(client, *, chat=True, review=True):
    settings(client)
    media = submit(client, translation={"mode": "on", "review": review})
    cid = None
    with session_factory()() as session:
        source = session.get(Run, media["id"])
        if chat:
            conversation = Conversation(model="fixture")
            session.add(conversation)
            session.flush()
            cid = conversation.id
            source.task.conversation_id = cid
            for run in session.scalars(select(Run).where(Run.task_id == source.task_id)):
                run.conversation_id = cid
            session.add_all(
                [
                    Message(
                        conversation_id=cid, role="user", content="Create a red bicycle", run_id=source.id
                    ),
                    Message(
                        conversation_id=cid,
                        role="assistant",
                        content="",
                        run_id=source.id,
                        metadata_json={"orchestration": True},
                    ),
                ]
            )
        tid = source.task_id
        session.commit()
    work()  # Actual worker + fake local translation, no image process.
    if cid:
        assert client.post(f"/api/chat/conversations/{cid}/tasks/{tid}/cancel").status_code == 200
    else:
        from app.task_control import cancel_task

        with session_factory()() as session:
            cancel_task(session, session.get(Task, tid))
            session.commit()
    assert read(client, media["id"])["status"] == "canceled"
    return media["id"], tid, cid


@pytest.mark.parametrize("choice", ["original", "retry", "reuse"])
@pytest.mark.parametrize("chat", [False, True])
def test_stopped_retry_preserves_old_fence_and_separates_intent(fake, choice, chat):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client, chat=chat, review=choice != "reuse")
        source = read(client, rid)
        body = {"translation": choice, "client_request_id": str(uuid4())}
        response = client.post(f"/api/images/runs/{rid}/retry", json=body)
        assert response.status_code == 202, response.text
        retry = response.json()
        ntid = retry["task_id"]
        nrid = retry["id"]
        assert ntid != tid and retry["parent_run_id"] is None
        assert retry["effective_permissions"] == source["effective_permissions"]
        assert retry["conversation_id"] == cid
        assert retry["metadata"][SOURCE] == {"run_id": rid, "task_id": tid}
        again = client.post(f"/api/images/runs/{rid}/retry", json=body)
        assert again.status_code == 202 and again.json()["id"] == nrid
        assert (
            client.post(
                f"/api/images/runs/{rid}/retry", json={**body, "client_request_id": str(uuid4())}
            ).status_code
            == 409
        )
        with session_factory()() as session:
            old = session.get(Task, tid)
            assert old.metadata_json["stop_requested_at"]
            assert not session.get(Task, ntid).metadata_json.get("stop_requested_at")
            with pytest.raises(HTTPException, match="stopped"):
                create_run(
                    session, old, run_type="image", capability="image.generate", executor_type="photo_pipe"
                )
        if cid:
            old_stop = client.post(f"/api/chat/conversations/{cid}/tasks/{tid}/cancel")
            assert old_stop.status_code == 200
            assert read(client, nrid)["status"] == "queued"
            messages = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
            assert len(messages) == 4 and messages[-1]["run_id"] == nrid
            assert messages[-2]["role"] == "user" and "new task" in messages[-2]["content"]
            assert "earlier task remains stopped" in messages[-1]["content"]
            assert messages[-1]["media_runs"][0]["id"] == nrid
            assert messages[1]["media_runs"][0]["id"] == rid
            assert messages[1]["media_runs"][0]["metadata"][FRESH]["run_id"] == nrid
        if choice == "retry":
            with session_factory()() as session:
                from app.task_control import cancel_task

                children = list(session.scalars(select(Run).where(Run.task_id == ntid)))
                assert any(r.executor_type == "media_translate" for r in children)
                cancel_task(session, session.get(Task, ntid))
                session.commit()
            assert read(client, nrid)["status"] == "canceled"
            assert fake[1] == []
        else:
            work()
            assert read(client, nrid)["status"] == "succeeded"
            assert fake[1][-1]["prompt"] == ("czerwony rower" if choice == "original" else "a red bicycle")
            if cid:
                last = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
                assert last["task_status"] == "succeeded"


def test_duplicate_requests_create_one_new_task_and_one_chat_turn(fake):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)
        body = {"translation": "original", "client_request_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(
                pool.map(lambda _: client.post(f"/api/images/runs/{rid}/retry", json=body), range(2))
            )
        assert [r.status_code for r in replies] == [202, 202]
        assert len({r.json()["id"] for r in replies}) == 1
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 2
            assert session.scalar(select(func.count()).select_from(Message)) == 4


def test_pending_native_completion_blocks_fresh_intent_without_side_effects(fake, monkeypatch):
    from app.runner_client import RunnerClient

    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)
        monkeypatch.setattr(
            RunnerClient, "inspect_process", lambda *_: {"alive": False, "completion_pending": True}
        )
        reply = client.post(f"/api/images/runs/{rid}/retry", json={"translation": "original"})
        assert reply.status_code == 409
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            assert FRESH not in session.get(Run, rid).metadata_json
            assert session.scalar(select(func.count()).select_from(Message)) == 2


def test_translation_enqueue_failure_rolls_back_new_task_and_messages(fake, monkeypatch):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)

        def fail(*args, **kwargs):
            raise ValueError("owned enqueue failure")

        monkeypatch.setattr("app.media_translation.enqueue_translation", fail)
        with pytest.raises(ValueError, match="owned enqueue failure"):
            client.post(f"/api/images/runs/{rid}/retry", json={"translation": "retry"})
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            assert FRESH not in session.get(Run, rid).metadata_json
            assert session.scalar(select(func.count()).select_from(Message)) == 2


@pytest.mark.parametrize("tamper", ["task_source", "run_request"])
def test_fresh_retry_binding_tamper_fails_closed(fake, tamper):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)
        body = {"translation": "original", "client_request_id": str(uuid4())}
        first = client.post(f"/api/images/runs/{rid}/retry", json=body)
        assert first.status_code == 202
        with session_factory()() as session:
            task = session.get(Task, first.json()["task_id"])
            if tamper == "task_source":
                task.metadata_json = {SOURCE: {"run_id": str(uuid4()), "task_id": tid}}
            else:
                retry = session.get(Run, first.json()["id"])
                retry.metadata_json = {
                    **retry.metadata_json,
                    "image_retry_request": {"id": str(uuid4()), "translation": "original"},
                }
            session.commit()
        assert client.post(f"/api/images/runs/{rid}/retry", json=body).status_code == 409
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 2


def test_verified_translation_reuse_survives_a_second_explicit_stopped_intent(fake):
    from app.task_control import cancel_task

    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client, review=False)
        first = client.post(
            f"/api/images/runs/{rid}/retry", json={"translation": "reuse", "client_request_id": str(uuid4())}
        )
        assert first.status_code == 202, first.text
        with session_factory()() as session:
            cancel_task(session, session.get(Task, first.json()["task_id"]))
            session.commit()
        second = client.post(
            f"/api/images/runs/{first.json()['id']}/retry",
            json={"translation": "reuse", "client_request_id": str(uuid4())},
        )
        assert second.status_code == 202, second.text
        work()
        assert read(client, second.json()["id"])["status"] == "succeeded"
        assert len(fake[0]) == 1 and fake[1][-1]["prompt"] == "a red bicycle"


def test_reused_receipt_is_reverified_in_worker_before_dispatch(fake):
    from app.config import get_settings
    from app.models import Artifact

    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client, review=False)
        response = client.post(f"/api/images/runs/{rid}/retry", json={"translation": "reuse"})
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            source = session.get(Run, rid)
            artifact = session.get(Artifact, source.metadata_json["prompt_translation"]["artifact_id"])
            (get_settings().data_dir / artifact.relative_path).write_text("{}")
        work()
        assert read(client, response.json()["id"])["status"] == "failed"
        assert fake[1] == []


def test_missing_image_input_does_not_create_a_fresh_task(fake):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)
        with session_factory()() as session:
            source = session.get(Run, rid)
            source.parameters = {**source.parameters, "inputs": ["uploads/missing.png"]}
            session.commit()
        response = client.post(f"/api/images/runs/{rid}/retry", json={"translation": "original"})
        assert response.status_code == 422, response.text
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            assert session.scalar(select(func.count()).select_from(Message)) == 2


def test_stop_during_native_inspection_forks_retry_without_reopening_old_task(fake, monkeypatch):
    from app.runner_client import RunnerClient, RunnerError
    from app.task_control import cancel_task

    with TestClient(app) as client:
        source = submit(client, translation={"mode": "off"})
        with session_factory()() as session:
            session.get(Run, source["id"]).status = "failed"
            session.commit()

        def inspect(*args):
            with session_factory()() as session:
                cancel_task(session, session.get(Task, source["task_id"]))
                session.commit()
            raise RunnerError(404, "No owned process")

        monkeypatch.setattr(RunnerClient, "inspect_process", inspect)
        response = client.post(f"/api/images/runs/{source['id']}/retry")
        assert response.status_code == 202, response.text
        assert response.json()["task_id"] != source["task_id"] and response.json()["parent_run_id"] is None
        with session_factory()() as session:
            assert session.get(Task, source["task_id"]).metadata_json["stop_requested_at"]


@pytest.mark.parametrize(
    "executor,capability,params",
    [
        ("wan_video", "video.generate", {"prompt": "A QA garden"}),
        ("ace_step_music", "music.generate", {"caption": "QA instrumental music"}),
    ],
)
@pytest.mark.parametrize("reused_receipt", [False, True])
def test_other_finished_media_retries_use_the_same_independent_stop_contract(
    fake, executor, capability, params, reused_receipt
):
    from app.runs import create_task
    from app.task_control import cancel_task

    with TestClient(app) as client, session_factory()() as session:
        task = create_task(session, title="Owned media", prompt="QA", capability=capability)
        run = create_run(
            session, task, run_type="media", capability=capability, executor_type=executor, parameters=params
        )
        if reused_receipt:
            field = "caption" if executor == "ace_step_music" else "prompt"
            run.metadata_json = {
                "prompt_translation": {
                    "status": "ready",
                    "original": {field: "Oryginalny opis QA"},
                    "effective": {field: params[field]},
                    "policy": {"model": "fixture", "target_language": "en"},
                    "reused_from_run_id": str(uuid4()),
                }
            }
        cancel_task(session, task)
        session.commit()
        response = client.post(
            f"/api/generation/media/{run.id}/retry",
            json={"translation": "original" if reused_receipt else "reuse"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["task_id"] != task.id and response.json()["parent_run_id"] is None
        if reused_receipt:
            assert "reused_from_run_id" not in response.json()["metadata"]["prompt_translation"]
            assert response.json()["parameters"][field] == "Oryginalny opis QA"
            from app.media_translation import validate_media_translation

            validate_media_translation(session, session.get(Run, response.json()["id"]))
        else:
            assert response.json()["parameters"] == params


@pytest.mark.parametrize("existing", [False, True])
def test_archived_conversation_blocks_new_intent_but_not_receipt_replay(fake, existing):
    with TestClient(app) as client:
        rid, tid, cid = stopped_media(client)
        body = {"translation": "original", "client_request_id": str(uuid4())}
        if existing:
            first = client.post(f"/api/images/runs/{rid}/retry", json=body)
            assert first.status_code == 202
            work()
        conversation = client.get(f"/api/chat/conversations/{cid}").json()
        archive = client.put(
            f"/api/chat/conversations/{cid}/archive",
            json={"archived": True, "expected_settings_version": conversation["settings_version"]},
        )
        assert archive.status_code == 200, archive.text
        with session_factory()() as session:
            before = (
                session.scalar(select(func.count()).select_from(Task)),
                session.scalar(select(func.count()).select_from(Message)),
            )
        response = client.post(f"/api/images/runs/{rid}/retry", json=body)
        assert response.status_code == (202 if existing else 409), response.text
        if existing:
            assert response.json()["id"] == first.json()["id"]
        with session_factory()() as session:
            assert before == (
                session.scalar(select(func.count()).select_from(Task)),
                session.scalar(select(func.count()).select_from(Message)),
            )
            assert session.get(Conversation, cid).archived_at is not None
