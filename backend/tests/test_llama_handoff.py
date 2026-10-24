"""Actual worker/dependency/resource contracts, synthetic owned model only."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.dependencies import depend_on
from app.engine import tick
from app.executors import EXECUTORS
from app.llama import evict_idle_models, instances
from app.llama_handoff import NAME
from app.models import ModelFile, Run, RunDependency, RuntimeInstance
from app.resources import active_locks, release_run_locks, reserve_gpu
from app.runner_client import RunnerClient
from app.runs import claim_next, create_run, create_task, request_cancel, transition
from app.state import RunStatus
from app.task_control import cancel_task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_llama import load, tick_once
from test_llama import managed as managed


def prepare(
    api, model_id, *, transitive=False, cross_task=False, count=1, load_settings=None, separate_tasks=False
):
    if load_settings:
        response = api.post(
            "/api/llama/load", json={"model_file_id": model_id, "gpus": [2, 7], **load_settings}
        )
        assert response.status_code == 202, response.text
    else:
        load(api, model_id)
    tick_once()
    with session_factory()() as db:
        original = instances(db)[0]
        task = create_task(db, title="Media then explanation", prompt="", capability="image.generate")
        image = create_run(
            db,
            task,
            run_type="image",
            capability="image.generate",
            executor_type="test_media",
            requested_gpu="auto",
        )
        prerequisite = image
        if transitive:
            prerequisite = create_run(
                db, task, run_type="test", capability="observation", executor_type="fake"
            )
            depend_on(db, prerequisite, image)
        future_task = (
            create_task(db, title="Explain media", prompt="", capability="chat.completion")
            if cross_task
            else task
        )
        consumers = []
        for _ in range(count):
            if separate_tasks:
                future_task = create_task(
                    db, title="Independent future", prompt="", capability="chat.completion"
                )
            consumer = create_run(
                db,
                future_task,
                run_type="chat",
                capability="chat.completion",
                executor_type="test_consumer",
                parameters={
                    "model": "llamacpp:" + model_id,
                    "endpoint": original.endpoint,
                },
                permissions=["filesystem_read"],
            )
            depend_on(db, consumer, prerequisite)
            consumers.append(consumer.id)
        evict_idle_models(db, image, [2, 7])
        db.commit()
        return image.id, consumers, original.id


class Media:
    name = "test_media"

    def execute(self, db, run):
        assert not active_locks(db), "Owned model must have yielded both GPU reservations"
        transition(db, run, RunStatus.PREPARING, event_type="test.preparing")
        assert reserve_gpu(db, run, [2, 7]) == "2"
        transition(db, run, RunStatus.RUNNING, event_type="test.started")
        release_run_locks(db, run.id)
        transition(db, run, RunStatus.SUCCEEDED, event_type="test.completed")


class Consumer:
    name = "test_consumer"

    def execute(self, db, run):
        endpoint = run.parameters["endpoint"]
        runtime = db.scalar(select(RuntimeInstance).where(RuntimeInstance.endpoint == endpoint))
        assert runtime.status == "ready" and active_locks(db) == {"gpu:2", "gpu:7"}
        for state in (RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED):
            transition(db, run, state, event_type="test.transition")


def step():
    with session_factory()() as db:
        return tick(
            db, "handoff-worker", executors={**EXECUTORS, "test_media": Media(), "test_consumer": Consumer()}
        )


def drain():
    for _ in range(20):
        if step() is None:
            return
    raise AssertionError("Fake workflow did not finish")


@pytest.mark.parametrize("transitive,cross_task,count", [(False, False, 1), (True, True, 2)])
def test_yield_media_lazy_reload_and_future_completion_preserve_preset_and_source(
    managed, monkeypatch, transitive, cross_task, count
):
    model_id, records = managed
    with TestClient(app) as api:
        image_id, consumers, old_id = prepare(
            api, model_id, transitive=transitive, cross_task=cross_task, count=count
        )
        with session_factory()() as db:
            old = db.get(RuntimeInstance, old_id)
            saved = {k: old.metadata_json[k] for k in ("model_file_id", "gpus", "context_size", "cache_type")}
            assert len(list(db.scalars(select(Run).where(Run.executor_type == NAME)))) == count
            assert not list(
                db.scalars(select(Run).where(Run.executor_type == "llama_load", Run.status == "queued"))
            )
            assert claim_next(db, "only-stop").executor_type == "llama_stop"
            db.rollback()
        assert step()  # owned stop
        assert step() == image_id
        if transitive:
            assert step()  # intermediate observation
        # No Runner I/O belongs to the pure preparation transaction.
        original = RunnerClient.hardware
        monkeypatch.setattr(
            RunnerClient, "hardware", lambda *a: pytest.fail("Preparation contacted native hardware")
        )
        assert step()  # first consumer preparation
        monkeypatch.setattr(RunnerClient, "hardware", original)
        drain()
        with session_factory()() as db:
            rows = list(db.scalars(select(Run)))
            assert all(run.status == "succeeded" for run in rows), [
                (r.executor_type, r.status, r.error_message) for r in rows
            ]
            ready = [item for item in instances(db) if item.status == "ready"]
            assert len(ready) == 1 and ready[0].id != old_id and len(records) == 2
            assert {k: ready[0].metadata_json[k] for k in saved} == saved
            for rid in consumers:
                consumer = db.get(Run, rid)
                assert consumer.parameters["endpoint"] == ready[0].endpoint
                assert consumer.parameters["model"] == "llamacpp:" + model_id
                assert consumer.effective_permissions == ["filesystem_read"]


@pytest.mark.parametrize("change", ["model", "prompt", "permission", "file", "preset", "unknown", "marker"])
def test_changed_source_or_authority_never_queues_reload(managed, change):
    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, old_id = prepare(api, model_id)
        step()
        assert step() == image
        with session_factory()() as db:
            consumer = db.get(Run, consumers[0])
            old = db.get(RuntimeInstance, old_id)
            if change in {"model", "prompt"}:
                consumer.parameters = {**consumer.parameters, change: "changed"}
            elif change == "permission":
                consumer.effective_permissions = ["external_ai"]
            elif change == "file":
                db.get(ModelFile, model_id).mtime += 1
            elif change == "preset":
                old.metadata_json = {**old.metadata_json, "context_size": 8192}
            elif change == "unknown":
                old.status = "unknown"
            else:
                consumer.metadata_json = {}
            db.commit()
        drain()
        with session_factory()() as db:
            resume = db.scalar(select(Run).where(Run.executor_type == NAME))
            assert resume.status == "failed" and db.get(Run, consumers[0]).status == "failed"
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
        assert len(records) == 1


@pytest.mark.parametrize("when", ["before_stop", "after_media", "expired", "failed_media", "whole_task"])
def test_stop_or_failed_prerequisite_does_not_restart_a_model(managed, when):
    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, _ = prepare(api, model_id)
        if when != "before_stop" and when != "whole_task":
            step()
        if when in {"after_media", "expired"}:
            step()
        with session_factory()() as db:
            consumer = db.get(Run, consumers[0])
            if when == "expired":
                consumer.parameters = {
                    **consumer.parameters,
                    "deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                }
            elif when == "whole_task":
                cancel_task(db, consumer.task)
            elif when == "failed_media":
                request_cancel(db, db.get(Run, image))
            else:
                request_cancel(db, consumer)
            db.commit()
        # Source media may still run for an independent consumer Stop; only
        # queued consumer restoration is forbidden.
        drain()
        with session_factory()() as db:
            assert db.get(Run, consumers[0]).status in {"canceled", "failed"}
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
        assert len(records) == 1


@pytest.mark.parametrize("change", ["stop", "expired"])
def test_restore_published_before_stop_or_expiry_never_dispatches_unused_model(managed, change):
    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, _ = prepare(api, model_id)
        step()
        assert step() == image
        assert step()  # Pure preparation queues the model, no native load yet.
        with session_factory()() as db:
            consumer = db.get(Run, consumers[0])
            if change == "expired":
                consumer.parameters = {
                    **consumer.parameters,
                    "deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                }
            else:
                request_cancel(db, consumer)
            db.commit()
        drain()
        assert len(records) == 1
        with session_factory()() as db:
            restored = db.scalar(
                select(Run).where(
                    Run.executor_type == "llama_load",
                    Run.metadata_json["runtime_handoff_resume_id"].as_string().is_not(None),
                )
            )
            assert restored.status == "canceled"


@pytest.mark.parametrize("cancel_media", [True, False])
def test_independent_conversation_has_no_media_dependency_and_survives_media_stop(
    managed, monkeypatch, cancel_media
):
    from app.local_provider import LocalChatProvider

    async def reply(self, **kwargs):
        yield "Independent reply."

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    model_id, records = managed
    with TestClient(app) as api:
        image, _, _ = prepare(api, model_id, cross_task=True)
        step()  # old model stop
        conv = api.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
        response = api.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"})
        assert response.status_code == 202, response.text
        chat = response.json()
        with session_factory()() as db:
            independent_load = db.scalar(
                select(Run).where(Run.executor_type == "llama_load", Run.status == "queued")
            )
            assert independent_load.task_id == chat["task_id"]
            assert db.get(RunDependency, (independent_load.id, image)) is None
            if cancel_media:
                cancel_task(db, db.get(Run, image).task)
                db.commit()
        drain()
        with session_factory()() as db:
            assert db.get(Run, chat["id"]).status == "succeeded"
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 2
        assert len(records) == 2


@pytest.mark.parametrize("state", ["queued", "claimed", "preparing", "running", "waiting_for_approval"])
def test_unrelated_or_active_consumer_still_protects_its_model(managed, state):
    model_id, _ = managed
    with TestClient(app) as api:
        load(api, model_id)
        tick_once()
        with session_factory()() as db:
            instance = instances(db)[0]
            task = create_task(db, title="Protected work", prompt="", capability="chat.completion")
            consumer = create_run(
                db,
                task,
                run_type="chat",
                capability="chat.completion",
                executor_type="chat",
                parameters={"model": "llamacpp:" + model_id, "endpoint": instance.endpoint},
            )
            image = create_run(
                db,
                task,
                run_type="image",
                capability="image.generate",
                executor_type="fake",
                requested_gpu="auto",
            )
            if state != "queued":
                depend_on(db, consumer, image)
            consumer.status = state
            evict_idle_models(db, image, [2, 7])
            assert instance.status == "ready"
            assert not list(db.scalars(select(Run).where(Run.executor_type.in_(["llama_stop", NAME]))))


def test_crash_before_atomic_preparation_commit_recovers_without_duplicate_load(managed, monkeypatch):
    from app import llama
    from app.llama_handoff import LlamaResumeConsumerExecutor
    from app.recovery import recover_stale

    model_id, records = managed
    with TestClient(app) as api:
        image, _, _ = prepare(api, model_id)
        step()
        assert step() == image
        original = llama.enqueue_load

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise SystemExit("Synthetic worker disappearance before commit")

        monkeypatch.setattr(llama, "enqueue_load", crash)
        with session_factory()() as db:
            resume = claim_next(db, "lost-worker")
            assert resume.executor_type == NAME
            rid = resume.id
            db.commit()
            with pytest.raises(SystemExit):
                LlamaResumeConsumerExecutor().execute(db, resume)
            db.rollback()
            assert db.get(Run, rid).status == "claimed"
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
            db.get(Run, rid).lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            assert rid in recover_stale(db)
            db.commit()
            assert db.get(Run, rid).status == "queued"
        monkeypatch.setattr(llama, "enqueue_load", original)
        drain()
        assert len(records) == 2
        with session_factory()() as db:
            assert db.get(Run, rid).status == "succeeded"
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 2


def test_repeat_eviction_does_not_publish_duplicate_preparations(managed):
    model_id, _ = managed
    with TestClient(app) as api:
        image, _, _ = prepare(api, model_id)
        with session_factory()() as db:
            evict_idle_models(db, db.get(Run, image), [2, 7])
            assert len(list(db.scalars(select(Run).where(Run.executor_type == NAME)))) == 1
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_stop")))) == 1


@pytest.mark.parametrize("shared", [False, True])
def test_expiry_during_native_startup_stops_only_an_unshared_owned_restore(managed, monkeypatch, shared):
    from app.local_provider import LocalChatProvider

    async def reply(self, **kwargs):
        yield "Shared model retained."

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, _ = prepare(api, model_id)
        step()
        assert step() == image
        step()  # consumer preparation
        if shared:
            conv = api.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
            response = api.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"})
            assert response.status_code == 202, response.text
            chat = response.json()
        original = RunnerClient.load_llama

        def expire(self, body):
            with session_factory()() as db:
                consumer = db.get(Run, consumers[0])
                consumer.parameters = {
                    **consumer.parameters,
                    "deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                }
                db.commit()
            return original(self, body)

        monkeypatch.setattr(RunnerClient, "load_llama", expire)
        drain()
        with session_factory()() as db:
            assert db.get(Run, consumers[0]).status == "canceled"
            if shared:
                assert db.get(Run, chat["id"]).status == "succeeded"
                assert active_locks(db) == {"gpu:2", "gpu:7"}
            else:
                assert not active_locks(db)
        assert len(records) == 2
        assert sum(record["alive"] for record in records.values()) == int(shared)


def test_previously_fitted_large_q8_context_is_reused_without_network_under_preparation_lock(
    managed, monkeypatch
):
    from app import llama

    monkeypatch.setattr(llama, "gpu_memory_totals", lambda *a: [24576, 24576])
    model_id, _ = managed
    with TestClient(app) as api:
        image, _, _ = prepare(api, model_id, load_settings={"context_size": 131072, "cache_type": "q8_0"})
        step()
        assert step() == image
        monkeypatch.setattr(
            llama, "gpu_memory_totals", lambda *a: pytest.fail("Preparation read native memory")
        )
        drain()
        with session_factory()() as db:
            ready = next(item for item in instances(db) if item.status == "ready")
            assert ready.metadata_json["context_size"] == 131072
            assert ready.metadata_json["cache_type"] == "q8_0" and ready.metadata_json["gpus"] == [2, 7]


@pytest.mark.parametrize("changed", [False, True])
def test_vision_companion_is_retained_and_changed_companion_cannot_be_loaded(managed, changed):
    model_id, records = managed
    with TestClient(app) as api:
        with session_factory()() as db:
            companion = ModelFile(
                host_path="/models/mmproj-model.gguf",
                filename="mmproj-model.gguf",
                format="gguf",
                category="llm",
                availability="present",
                size_bytes=12,
                mtime=2,
            )
            db.add(companion)
            db.commit()
            pid = companion.id
        image, _, _ = prepare(api, model_id, load_settings={"projector_file_id": pid})
        step()
        assert step() == image
        if changed:
            with session_factory()() as db:
                db.get(ModelFile, pid).mtime += 1
                db.commit()
        drain()
        with session_factory()() as db:
            resume = db.scalar(select(Run).where(Run.executor_type == NAME))
            assert resume.status == ("failed" if changed else "succeeded"), resume.error_message
            if not changed:
                ready = next(item for item in instances(db) if item.status == "ready")
                assert ready.metadata_json["projector_file_id"] == pid
        assert len(records) == (1 if changed else 2)


def test_preparation_requires_its_own_model_management_permission(managed):
    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, _ = prepare(api, model_id)
        step()
        assert step() == image
        with session_factory()() as db:
            resume = db.scalar(select(Run).where(Run.executor_type == NAME))
            resume.effective_permissions = ["filesystem_read"]
            db.commit()
        drain()
        with session_factory()() as db:
            assert db.get(Run, consumers[0]).status == "failed"
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
        assert len(records) == 1


def test_public_model_loading_cannot_request_the_internal_fitted_preset_option(managed):
    model_id, _ = managed
    with TestClient(app) as api:
        response = api.post(
            "/api/llama/load", json={"model_file_id": model_id, "gpus": [2, 7], "_fitted_context": True}
        )
        assert response.status_code == 422
        with session_factory()() as db:
            assert not list(db.scalars(select(Run)))


def test_large_dependency_frontier_does_not_widen_model_eviction(session):
    from uuid import uuid4

    from app.llama_handoff import waits_for
    from sqlalchemy import insert

    task = create_task(session, title="Bounded graph", prompt="", capability="test")
    consumer = create_run(session, task, run_type="test", capability="test", executor_type="fake")
    ids = [str(uuid4()) for _ in range(1025)]
    session.execute(
        insert(Run),
        [
            {
                "id": rid,
                "task_id": task.id,
                "run_type": "test",
                "capability": "test",
                "executor_type": "fake",
                "execution_target": "container",
                "status": "queued",
            }
            for rid in ids
        ],
    )
    session.execute(insert(RunDependency), [{"run_id": consumer.id, "prerequisite_id": rid} for rid in ids])
    assert waits_for(session, consumer.id, ids[0]) is False


def test_two_workers_prepare_separate_tasks_with_one_shared_restore(managed):
    from concurrent.futures import ThreadPoolExecutor

    model_id, records = managed
    with TestClient(app) as api:
        image, consumers, _ = prepare(api, model_id, count=2, separate_tasks=True)
        step()
        assert step() == image

        def prepare_one(index):
            with session_factory()() as db:
                return tick(
                    db,
                    f"parallel-handoff-{index}",
                    executors={**EXECUTORS, "test_media": Media(), "test_consumer": Consumer()},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(prepare_one, range(2)))
        assert len(set(results)) == 2
        with session_factory()() as db:
            assert all(db.get(Run, rid).executor_type == NAME for rid in results)
            assert all(db.get(Run, rid).status == "succeeded" for rid in results)
            loads = list(
                db.scalars(select(Run).where(Run.executor_type == "llama_load", Run.status == "queued"))
            )
            assert len(loads) == 1
            assert all(db.get(RunDependency, (rid, loads[0].id)) is not None for rid in consumers)
        drain()
        assert len(records) == 2


def test_retained_shared_startup_can_still_reclaim_idle_gpus_after_its_original_task_stops(
    managed, monkeypatch
):
    from app.local_provider import LocalChatProvider

    async def reply(self, **kwargs):
        yield "Independent conversation continues."

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    model_id, _ = managed
    with TestClient(app) as api:
        other_id, conversations, messages = blocked_startup(api, model_id, count=2)
        stopped = api.post(
            f"/api/chat/conversations/{conversations[0]['id']}/tasks/{messages[0]['task_id']}/cancel"
        )
        assert stopped.status_code == 200 and stopped.json()["retained_run_ids"], stopped.text
        drain()
        with session_factory()() as db:
            assert db.get(Run, messages[1]["id"]).status == "succeeded", [
                (run.executor_type, run.status, run.error_type, run.error_message)
                for run in db.scalars(select(Run))
            ]
            assert active_locks(db) == {"gpu:2", "gpu:7"}
            old = next(item for item in instances(db) if item.metadata_json["model_file_id"] == other_id)
            assert old.status == "stopped"


def blocked_startup(api, model_id, *, count):
    with session_factory()() as db:
        other = ModelFile(
            host_path="/models/idle-other.gguf",
            filename="idle-other.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        db.add(other)
        db.commit()
        other_id = other.id
    load(api, other_id)
    tick_once()
    conversations = [
        api.post("/api/chat/conversations", json={"model": "llamacpp:" + model_id}).json()
        for _ in range(count)
    ]
    messages = [
        api.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"}).json()
        for conv in conversations
    ]
    return other_id, conversations, messages


@pytest.mark.parametrize("another_waits_for_stop", [False, True])
def test_automatic_eviction_after_last_original_consumer_stops_preserves_new_dependents(
    managed, monkeypatch, another_waits_for_stop
):
    from app.llama import reconcile
    from app.local_provider import LocalChatProvider

    async def reply(self, **kwargs):
        yield "New dependent survives."

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    model_id, records = managed
    with TestClient(app) as api:
        bid, conversations, messages = blocked_startup(api, model_id, count=2)
        stopped = api.post(
            f"/api/chat/conversations/{conversations[0]['id']}/tasks/{messages[0]['task_id']}/cancel"
        )
        assert stopped.status_code == 200
        step()  # retained load queues a separate resource-support stop
        if another_waits_for_stop:
            conv = api.post("/api/chat/conversations", json={"model": "llamacpp:" + bid}).json()
            new = api.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"}).json()
        stopped = api.post(
            f"/api/chat/conversations/{conversations[1]['id']}/tasks/{messages[1]['task_id']}/cancel"
        )
        assert stopped.status_code == 200
        drain()
        with session_factory()() as db:
            reconcile(db, RunnerClient())
            if another_waits_for_stop:
                assert db.get(Run, new["id"]).status == "succeeded"
                assert len(records) == 2
            else:
                assert len(records) == 1 and next(iter(records.values()))["alive"]
                old = next(item for item in instances(db) if item.metadata_json["model_file_id"] == bid)
                assert old.status == "ready"
            assert not list(
                db.scalars(select(Run).where(Run.status.in_(["queued", "claimed", "preparing", "running"])))
            )


def test_task_stop_retains_automatic_model_stop_needed_by_a_new_conversation(managed, monkeypatch):
    from app.local_provider import LocalChatProvider

    async def reply(self, **kwargs):
        yield "Required stop retained."

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    model_id, records = managed
    with TestClient(app) as api:
        bid, conversations, messages = blocked_startup(api, model_id, count=1)
        step()  # source load cannot reserve GPUs and queues an owned stop
        with session_factory()() as db:
            owned_stop = db.scalar(
                select(Run).where(Run.executor_type == "llama_stop", Run.status == "queued")
            )
            stop_id = owned_stop.id
        conv = api.post("/api/chat/conversations", json={"model": "llamacpp:" + bid}).json()
        new = api.post(f"/api/chat/conversations/{conv['id']}/messages", json={"content": "Hello"}).json()
        stopped = api.post(
            f"/api/chat/conversations/{conversations[0]['id']}/tasks/{messages[0]['task_id']}/cancel"
        )
        assert stopped.status_code == 200 and stop_id in stopped.json()["retained_run_ids"]
        drain()
        with session_factory()() as db:
            assert db.get(Run, new["id"]).status == "succeeded"
            assert db.get(Run, stop_id).status == "succeeded"
        assert len(records) == 2
