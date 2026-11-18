import json
from datetime import timedelta

from app.api import app
from app.db import utcnow
from app.embedding_models import MODEL_ID
from app.embeddings import MemoryEmbedExecutor, content_hash, load_setup, save_setup, vector_identity
from app.memory import upsert_memory
from app.models import MemoryEmbedding, MemoryEntry, Run
from app.personal_memory import protect, queue_index, recalled, schedule_capture, schedule_recall
from app.recovery import recover_stale
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_managed_embeddings import cpu as cpu
from test_managed_embeddings import installed as installed
from test_personal_memory import capture, consent, consumer, execute, fake_proposal, source


def test_actual_owned_cpu_child_supplies_semantic_recall_and_is_stopped(session, cpu):
    source_run, _, _ = source(session)
    entry = upsert_memory(session, scope="global", content="Pear harvest is my hobby")
    save_setup(
        session,
        {
            "backend": "local_cpu",
            "revision": 1,
            "model_id": MODEL_ID,
            "model": MODEL_ID,
            "dimension": 384,
            "endpoint": "",
            "secret_ref": "",
        },
    )
    vector = [0.0] * 384
    vector[1] = 1.0
    session.add(
        MemoryEmbedding(
            memory_id=entry.id,
            vector=vector,
            dimension=384,
            model=vector_identity(load_setup(session)),
            content_hash=content_hash(entry.content),
            source_run_id=source_run.id,
        )
    )
    session.commit()
    run, conversation, _ = consumer(session)
    recall = schedule_recall(session, run, conversation, "Pear")
    execute(session, recall)
    assert recall.status == "succeeded", recall.error_message
    result = recalled(session, run)
    assert result["method"] == "profile+lexical+semantic"
    assert [row["id"] for row in result["sources"]] == [entry.id]
    assert len(cpu) == 1 and recall.metadata_json["cpu_process_confirmed_gone"]


def test_missing_encoder_falls_back_without_losing_personal_context(session):
    upsert_memory(session, scope="global", content="My name is Alex")
    save_setup(
        session,
        {
            "backend": "local_cpu",
            "revision": 1,
            "model_id": MODEL_ID,
            "model": MODEL_ID,
            "dimension": 384,
            "endpoint": "",
            "secret_ref": "",
        },
    )
    session.commit()
    run, conversation, _ = consumer(session)
    recall = schedule_recall(session, run, conversation, "name")
    execute(session, recall)
    assert recall.status == "succeeded", recall.error_message
    assert recalled(session, run)["method"] == "profile+lexical+encoder-unavailable"
    assert "Alex" in recalled(session, run)["sources"][0]["content"]


def test_updates_during_index_coalesce_into_one_followup(session, cpu):
    upsert_memory(session, scope="global", content="Apples")
    save_setup(
        session,
        {
            "backend": "local_cpu",
            "revision": 1,
            "model_id": MODEL_ID,
            "model": MODEL_ID,
            "dimension": 384,
            "endpoint": "",
            "secret_ref": "",
        },
    )
    queue_index(session, None)
    first = session.scalar(select(Run).where(Run.executor_type == "memory_embed"))
    queue_index(session, None)
    queue_index(session, None)
    assert first.metadata_json["personal_memory_reindex"] is True
    assert len(list(session.scalars(select(Run)))) == 1
    transition(session, first, RunStatus.CLAIMED, event_type="run.claimed")
    first.worker_id = "index-fixture"
    session.commit()
    MemoryEmbedExecutor().execute(session, first)
    session.commit()
    assert first.status == "succeeded", first.error_message
    runs = list(session.scalars(select(Run)))
    assert len(runs) == 2
    assert load_setup(session)["last_index_run_id"] != first.id


def test_manual_edit_during_inference_wins(session, monkeypatch):
    consent(session, learn=True)
    capture(session, monkeypatch)
    entry = session.scalar(select(MemoryEntry))
    source_run, _, _ = source(session, "My name is Robin")
    run = schedule_capture(session, source_run)

    async def infer(*args, **kwargs):
        upsert_memory(session, scope="global", entry_id=entry.id, content="Keep initials only")
        protect(entry)
        session.commit()
        return json.dumps(
            {
                "memories": [
                    {
                        "topic": "user.name",
                        "kind": "fact",
                        "quote": "My name is Robin",
                        "content": "Robin",
                        "target_id": entry.id,
                    }
                ]
            }
        )

    monkeypatch.setattr("app.assistant_decisions.infer", infer)
    execute(session, run)
    assert run.status == "succeeded" and entry.content == "Keep initials only"


def test_conversation_optout_and_history_explicit_batches(session, monkeypatch):
    source_run, conversation, _ = source(session)
    session.commit()
    api = TestClient(app)
    assert api.post("/api/memory/personal/history").status_code == 409
    consent(session, learn=True)
    response = api.post("/api/memory/personal/history")
    assert response.status_code == 202, response.text
    run = session.get(Run, response.json()["id"])
    execute(session, run)
    children = run.metadata_json["capture_run_ids"]
    assert len(children) == 1
    fake_proposal(monkeypatch)
    execute(session, session.get(Run, children[0]))
    session.commit()
    # No reimport of already processed evidence.
    repeated = api.post("/api/memory/personal/history")
    run = session.get(Run, repeated.json()["id"])
    execute(session, run)
    assert run.metadata_json["capture_run_ids"] == []
    conversation.personal_memory = False
    session.commit()
    assert schedule_capture(session, source_run) is None


def test_success_transition_queues_once_and_capture_does_not_block_another_turn(session, monkeypatch):
    consent(session, learn=True)
    run, conversation, message = source(session)
    run.status = "running"
    session.commit()
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    assert message.metadata_json["personal_memory_capture"]["run_id"]
    session.commit()
    from app.chat import ensure_idle

    ensure_idle(session, conversation.id)


def test_recovery_of_pure_local_capture_is_bounded_and_preserves_consent_fence(session):
    consent(session, learn=True)
    source_run, _, _ = source(session)
    run = schedule_capture(session, source_run)
    transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    transition(session, run, RunStatus.RUNNING, event_type="executor.started")
    run.worker_id = "gone"
    run.lease_expires_at = utcnow() - timedelta(seconds=10)
    session.commit()

    class NoRunner:
        def inspect_process(self, *_):
            raise AssertionError("Pure local work must not inspect host processes")

    assert run.id in recover_stale(session, NoRunner())
    assert run.status == "queued" and run.metadata_json["memory_recoveries"] == 1
    consent(session, learn=False, revision=1)
    execute(session, run)
    assert run.status == "canceled"


def test_stopped_history_batch_can_resume_without_relearning_processed_turns(session, monkeypatch):
    source(session)
    consent(session, learn=True)
    api = TestClient(app)
    first = api.post("/api/memory/personal/history").json()
    parent = session.get(Run, first["id"])
    execute(session, parent)
    queued = parent.metadata_json["capture_run_ids"]
    session.commit()
    stopped = api.post(f"/api/memory/personal/runs/{queued[0]}/cancel")
    assert stopped.status_code == 200, stopped.text
    resumed = api.post("/api/memory/personal/history").json()
    next_parent = session.get(Run, resumed["id"])
    execute(session, next_parent)
    fresh = next_parent.metadata_json["capture_run_ids"]
    assert len(fresh) == 1 and fresh != queued
    fake_proposal(monkeypatch)
    execute(session, session.get(Run, fresh[0]))
    assert len(list(session.scalars(select(MemoryEntry)))) == 1
