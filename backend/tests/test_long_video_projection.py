"""Long queues keep their complete final result; no model inference or real video."""

from datetime import datetime
from uuid import uuid4

import pytest
from app.api import app
from app.artifacts import register_file
from app.assistant import task_results
from app.assistant_controller_tools import observation, wrapper_parameters
from app.db import session_factory, utcnow
from app.media_jobs import LongVideoRequest, publish_video
from app.models import Conversation, Message, Run
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import submit
from test_assistant_react_workflow import react_model as react_model
from test_media_jobs import bridge as bridge


def test_five_minute_queue_covers_every_frame_and_whole_stop_cancels_without_generation(bridge):
    with TestClient(app) as api:
        response = api.post(
            "/api/media/jobs/video",
            json={
                "client_request_id": str(uuid4()),
                "prompt": "A slow coastal study",
                "duration_seconds": 300,
            },
        )
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        with session_factory()() as db:
            from app.models import Task

            task = db.get(Task, tid)
            timing = task.metadata_json["media_plan"]["timing"]
            assert (
                timing["target_frames"] == 7200
                and sum(s["output_frames"] for s in timing["segments"]) == 7200
            )
            assert 40 < len(timing["segments"]) < 128
        stopped = api.post(f"/api/media/jobs/{tid}/cancel")
        assert stopped.status_code == 200, stopped.text
        with session_factory()() as db:
            assert {r.status for r in db.scalars(select(Run).where(Run.task_id == tid))} == {"canceled"}
        assert bridge == []


@pytest.mark.parametrize("separate_task", [False, True])
def test_final_film_survives_many_internal_artifacts_and_bounded_recent_activity(
    bridge, tmp_path, separate_task
):
    # Synthetic completed rows exercise publication/provenance only, not media quality.
    with session_factory()() as db:
        conv = Conversation(
            title="Synthetic long film",
            provider="local-openai-compatible",
            model="test-model",
            execution_mode="assistant",
        )
        db.add(conv)
        db.flush()
        root_task = create_task(
            db,
            title="Synthetic request",
            prompt="A long film",
            capability="assistant",
            conversation_id=conv.id,
        )
        root = create_run(
            db,
            root_task,
            run_type="orchestration",
            capability="assistant",
            executor_type="assistant_controller",
            execution_target="container",
        )
        wrapped = create_task(
            db,
            title="Synthetic tool",
            prompt="Long video",
            capability="assistant.tool",
            conversation_id=conv.id,
        )
        wrapper = create_run(
            db,
            wrapped,
            run_type="orchestration",
            capability="assistant.tool",
            executor_type="orchestrator",
            execution_target="container",
            parent_run_id=root.id,
        )
        queue = (
            create_task(
                db,
                title="Synthetic media",
                prompt="Long video",
                capability="video.long",
                conversation_id=conv.id,
            )
            if separate_task
            else wrapped
        )
        publish_video(
            db,
            LongVideoRequest(client_request_id=uuid4(), prompt="A slow coastal study", duration_seconds=300),
            task=queue,
            parent_run_id=wrapper.id,
            _prepare_translation=False,
        )
        plan = queue.metadata_json["media_plan"]
        ids = plan["segment_run_ids"] + [plan["compose_run_id"]]
        source = tmp_path / "synthetic.txt"
        source.write_text("Synthetic fixture bytes, not a qualified video")
        for rid in ids:
            row = db.get(Run, rid)
            row.status = "succeeded"
            row.finished_at = utcnow()
            artifact = register_file(
                db,
                source=source,
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="synthetic.mp4",
                run_id=rid,
                metadata={"internal_media": rid != plan["compose_run_id"]},
            )
        wrapper.status = "succeeded"
        if separate_task:
            wrapper.metadata_json = {"child_run_id": ids[0]}
        queue.metadata_json = {
            **queue.metadata_json,
            "media_plan": {**plan, "final_artifact_id": artifact.id},
        }
        message = Message(
            conversation_id=conv.id,
            role="assistant",
            content="Synthetic completed film",
            run_id=wrapper.id,
            metadata_json={"orchestration": True},
        )
        db.add(message)
        db.commit()
        projected = task_results(db, message, wrapper)
        assert [a["id"] for a in projected["artifacts"]] == [artifact.id]
        assert plan["compose_run_id"] in {s["id"] for s in projected["steps"]}
        active, result = observation(db, root, {"index": 1, "tool": "video.generate", "run_id": wrapper.id})
        assert not active and result["status"] == "succeeded", result
        assert len(result["artifacts"]) == 1 and result["artifacts"][0]["snapshot"]["id"] == artifact.id
        assert result["produced_types"] == ["video"]


def test_chat_tool_accepts_the_same_duration_bound_and_has_a_long_workflow_budget(react_model):
    with TestClient(app) as api:
        queued = submit(api, "Create a five minute coastal film")
        with session_factory()() as db:
            root = db.get(Run, queued["run"]["id"])
            deadline = datetime.fromisoformat(root.parameters["execution_deadline_at"])
            assert (deadline - root.created_at).total_seconds() > 23 * 3600
            value = wrapper_parameters(
                db, root, "video.generate", {"instruction": "A coastal film", "duration_seconds": 300}
            )
            assert value["media"]["duration_seconds"] == 300
            with pytest.raises(ValueError, match="300"):
                wrapper_parameters(
                    db, root, "video.generate", {"instruction": "A coastal film", "duration_seconds": 301}
                )


def test_creative_deadline_is_finite_and_cannot_be_injected_into_public_video_settings():
    from datetime import timedelta

    from app.media_jobs import execution_budget
    from pydantic import ValidationError

    expires = (utcnow() + timedelta(hours=23)).isoformat()
    assert execution_budget(expires) == {"execution_deadline_at": expires}
    with pytest.raises(ValueError, match="twenty-four"):
        execution_budget((utcnow() + timedelta(hours=25)).isoformat())
    with pytest.raises(ValidationError):
        LongVideoRequest(
            client_request_id=uuid4(), prompt="A film", duration_seconds=300, execution_deadline_at=expires
        )


def test_long_workflow_keeps_the_individual_native_process_ceiling(monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.host_media_executor import HostMediaExecutor

    now = utcnow()
    monkeypatch.setattr("app.host_media_executor.time.time", lambda: now.timestamp())
    run = SimpleNamespace(parameters={"execution_deadline_at": (now + timedelta(hours=24)).isoformat()})
    assert HostMediaExecutor.native_budget(run) == {"deadline_at": now.timestamp() + 4 * 3600}
    run.parameters = {"execution_deadline_at": (now + timedelta(minutes=3)).isoformat()}
    assert HostMediaExecutor.native_budget(run) == {"deadline_at": now.timestamp() + 180}


@pytest.mark.parametrize("tool,hours", [("system.inspect", 4), ("video.generate", 24)])
def test_long_controller_keeps_ordinary_tool_budgets_and_expands_only_video(react_model, tool, hours):
    from app.assistant_controller import dispatch
    from app.assistant_decisions import Decision

    with TestClient(app) as api:
        queued = submit(api, "A creative workflow")
        with session_factory()() as db:
            root = db.get(Run, queued["run"]["id"])
            root.status = "running"
            args = {"instruction": "A creative workflow"}
            if tool == "video.generate":
                args["duration_seconds"] = 300
            dispatch(
                db,
                root,
                Decision(kind="tool", reason="Create the requested result", tool=tool, arguments=args),
            )
            child = db.get(Run, root.metadata_json["controller_steps"][0]["run_id"])
            remaining = (
                datetime.fromisoformat(child.parameters["execution_deadline_at"]) - utcnow()
            ).total_seconds()
            assert (hours * 3600) - 30 < remaining <= hours * 3600
