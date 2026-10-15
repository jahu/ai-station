from uuid import uuid4

import av
import pytest
from app.api import app
from app.db import session_factory
from app.media_jobs import LongVideoRequest
from app.models import Artifact, Run, RunDependency, Task
from app.resources import active_locks
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_parallel_media_shots import bridge as bridge
from test_parallel_media_shots import stage_ids, view, work


def request():
    return {
        "client_request_id": str(uuid4()),
        "prompt": "Warm cinematic light",
        "composition_mode": "shots",
        "duration_seconds": 6,
        "width": 128,
        "height": 128,
        "steps": 4,
        "scenes": [
            {"prompt": "Opening forest", "duration_seconds": 2},
            {"prompt": "Closing ocean", "duration_seconds": 4},
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"composition_mode": "continuous"},
        {"duration_seconds": 7},
        {"scenes": []},
        {"scenes": [{"prompt": " ", "duration_seconds": 6}]},
        {"scenes": [{"prompt": "One", "duration_seconds": True}]},
        {"scenes": [{"prompt": "One", "duration_seconds": 1}] * 21},
        {"prompt": "x" * 1999},
    ],
)
def test_storyboard_rejects_ambiguous_or_oversized_plans(change):
    with pytest.raises(ValidationError):
        LongVideoRequest.model_validate({**request(), **change})


def test_storyboard_partitions_prompts_and_exact_frames_then_composes_real_cpu_output(bridge):
    with TestClient(app) as client:
        body = request()
        r = client.post("/api/media/jobs/video", json=body)
        assert r.status_code == 202, r.text
        tid = r.json()["task_id"]
        ids, composition = stage_ids(client, tid)
        assert len(ids) == 3
        assert client.post("/api/media/jobs/video", json=body).json() == r.json()
        changed = {**body, "scenes": [*body["scenes"]]}
        changed["scenes"][1] = {**changed["scenes"][1], "prompt": "Different ending"}
        assert client.post("/api/media/jobs/video", json=changed).status_code == 409
        with session_factory()() as session:
            rows = [session.get(Run, rid) for rid in ids]
            assert [x.parameters["scene_index"] for x in rows] == [0, 1, 1]
            assert [x.parameters["media_segment"]["output_frames"] for x in rows] == [48, 81, 15]
            assert [x.parameters["prompt"] for x in rows] == [
                "Warm cinematic light\n\nOpening forest",
                "Warm cinematic light\n\nClosing ocean",
                "Warm cinematic light\n\nClosing ocean",
            ]
            assert len({x.parameters["seed"] for x in rows}) == 3
            assert {
                (x.run_id, x.prerequisite_id)
                for x in session.scalars(
                    select(RunDependency).where(RunDependency.run_id.in_([*ids, composition]))
                )
            } == {(composition, rid) for rid in ids}
        assert [(x["completed_segments"], x["total_segments"]) for x in r.json()["scenes"]] == [
            (0, 1),
            (0, 2),
        ]
        work("opening")
        current = view(client, tid)
        assert current["scenes"][0]["status"] == "succeeded" and current["scenes"][1]["status"] == "queued"
        work("closing-first")
        work("closing-last")
        work("compose")
        result = view(client, tid)
        assert result["status"] == "succeeded" and all(x["status"] == "succeeded" for x in result["scenes"])
        with session_factory()() as session:
            artifact = session.get(Artifact, result["final_artifact_id"])
            assert artifact.metadata_json["scenes"] == body["scenes"]
            assert artifact.metadata_json["prompt"] == body["prompt"]
            expected = [
                session.scalar(
                    select(Artifact.id).where(Artifact.run_id == rid, Artifact.artifact_type == "video")
                )
                for rid in ids
            ]
            assert artifact.parent_artifact_ids == expected and not active_locks(session)
            from app.config import get_settings

            with av.open(str(get_settings().data_dir / artifact.relative_path)) as movie:
                frames = list(movie.decode(video=0))
                assert len(frames) == 144
                assert abs(float(frames[-1].time) - 143 / 24) < 0.001
                values = [bytes(frame.reformat(format="yuv420p").planes[0])[0] for frame in frames]
                assert values[47] > values[48] + 20 and values[128] > values[129] + 30


def test_resume_preserves_scene_identity_and_legacy_receipts_still_replay(bridge):
    with TestClient(app) as client:
        body = request()
        r = client.post("/api/media/jobs/video", json=body)
        assert r.status_code == 202
        tid = r.json()["task_id"]
        old, _ = stage_ids(client, tid)
        work("opening")
        assert client.post("/api/media/jobs/" + tid + "/cancel").status_code == 200
        r = client.post(
            "/api/media/jobs/" + tid + "/resume",
            json={"expected_revision": 1, "client_request_id": str(uuid4())},
        )
        assert r.status_code == 202, r.text
        # Stage history includes old attempts; use the selected plan for assertions.
        with session_factory()() as session:
            plan = session.get(Task, tid).metadata_json["media_plan"]
            assert plan["segment_run_ids"][0] == old[0]
            rows = [session.get(Run, rid) for rid in plan["segment_run_ids"]]
            assert [x.parameters["scene_index"] for x in rows] == [0, 1, 1]
            assert rows[1].id != old[1] and rows[1].parameters["prompt"].endswith("Closing ocean")
        assert r.json()["scenes"][0]["status"] == "succeeded"
        legacy = {key: value for key, value in request().items() if key != "scenes"}
        response = client.post("/api/media/jobs/video", json=legacy)
        assert response.status_code == 202 and "scenes" not in response.json()["request"]
        assert client.post("/api/media/jobs/video", json={**legacy, "scenes": None}).json() == response.json()
