"""A media handoff must reclaim an idle model before requiring free host RAM."""

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run, RuntimeInstance
from app.resources import active_locks
from app.runner_client import RunnerClient
from app.runs import claim_next, create_run, create_task, transition
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_llama import load, tick_once
from test_llama import managed as managed
from test_music import body
from test_music import music_bridge as music_bridge


@pytest.mark.parametrize("busy_consumer", [False, True])
def test_memory_wait_stops_only_an_idle_owned_model_before_media_dispatch(
    managed, music_bridge, monkeypatch, busy_consumer
):
    model_id, native = managed

    def hardware(_):
        ready = any(item["status"] == "ready" for item in native.values())
        return {"gpus": [{"index": 2}, {"index": 7}], "memory": {"available_mib": 12272 if ready else 65536}}

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with TestClient(app) as api:
        load(api, model_id)
        tick_once()
        with session_factory()() as session:
            instance = session.scalar(select(RuntimeInstance).where(RuntimeInstance.ownership == "managed"))
            session.add(
                RuntimeInstance(
                    runtime_key="external",
                    name="Unrelated service",
                    ownership="external",
                    status="ready",
                    metadata_json={"gpus": [7]},
                )
            )
            if busy_consumer:
                task = create_task(
                    session, title="Active conversation", prompt="", capability="chat.complete"
                )
                create_run(
                    session,
                    task,
                    run_type="chat",
                    capability="chat.complete",
                    executor_type="fake",
                    parameters={"endpoint": instance.endpoint},
                )
                consumer = claim_next(session, "other-consumer")
                transition(session, consumer, "preparing", event_type="executor.preparing")
                transition(session, consumer, "running", event_type="executor.started")
            session.commit()
        response = api.post("/api/audio/music/runs", json=body(gpu="7"))
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            assert tick(session, "media-handoff") == rid
            media = session.get(Run, rid)
            assert media.status == "queued" and not media.metadata_json.get("dispatch_attempted")
            stops = list(session.scalars(select(Run).where(Run.executor_type == "llama_stop")))
            assert len(stops) == (0 if busy_consumer else 1)
            if busy_consumer:
                assert session.get(RuntimeInstance, instance.id).status == "ready"
                return
            assert stops[0].task_id == media.task_id
            assert active_locks(session) == {"gpu:2", "gpu:7"}
            stop_id = stops[0].id
        assert tick_once() == stop_id
        assert tick_once() == rid
        with session_factory()() as session:
            assert session.get(Run, rid).status == "succeeded"
            assert not active_locks(session)
            assert (
                session.scalar(select(RuntimeInstance).where(RuntimeInstance.ownership == "external")).status
                == "ready"
            )
        assert len(api.get("/api/artifacts", params={"run_id": rid}).json()) == 1
