"""Public recurrent jobs use fake native generation and actual CPU MP4 composition."""

import hashlib
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import av
import pytest
from app import media_jobs, video
from app.api import app
from app.artifacts import register_file
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.executors import EXECUTORS
from app.models import Artifact, Run, Task
from app.resources import active_locks
from app.svi_executor import GEOMETRY, NAME, PROFILE, RAM_MIB
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_svi_worker import FakeNative


def body(source, **changes):
    return {
        "client_request_id": str(uuid4()),
        "prompt": "A paper boat floats across a pond",
        "image_artifact_id": source,
        "duration_seconds": 10,
        **{k: v for k, v in GEOMETRY.items() if k not in {"fps", "frames"}},
        "translation": {"mode": "off"},
        **changes,
    }


def write_clip(path, color, *, width=832, height=480):
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as target:
        stream = target.add_stream("libx264", rate=15)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.codec_context.thread_count = 2
        stream.options = {"preset": "ultrafast", "crf": "0"}
        for n in range(81):
            frame = av.VideoFrame(width, height, "yuv420p")
            for plane in frame.planes:
                plane.update(bytes([color + n % 10]) * plane.buffer_size)
            for packet in stream.encode(frame):
                target.mux(packet)
        for packet in stream.encode():
            target.mux(packet)


@pytest.fixture
def bridge(monkeypatch, request):
    from ai_station_runner.media_compose_job import compose

    runtime = {"profile": PROFILE, "manifest_sha256": "a" * 64, "environment_id": "b" * 64}
    profile = {
        "available": True,
        "backend": "wan22-svi-pro-q4",
        **{k: v for k, v in GEOMETRY.items() if k != "frames"},
        "native_window_frames": 81,
        "continuation_frames": 4,
        "memory_estimate_mib": RAM_MIB,
        "managed_runtime": runtime,
        "eligible_gpu_indices": [7],
    }
    if getattr(request, "param", "landscape") == "portrait":
        profile.update(
            width=480,
            height=832,
            generation_profiles=[
                {"id": "landscape", "width": 832, "height": 480},
                {"id": "portrait", "width": 480, "height": 832},
            ],
        )
    monkeypatch.setattr(video, "capabilities", lambda: profile)
    monkeypatch.setattr(media_jobs, "capabilities", lambda: profile)

    class Native(FakeNative):
        def request(self, method, path, payload):
            root = get_settings().data_dir
            if path == "/v1/runs/svi":
                result = super().request(method, path, payload)
                rid = payload["run_id"]
                base = root / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}"
                report = json.loads(base.with_suffix(".json").read_text())
                write_clip(
                    base.with_suffix(".mp4"),
                    30 + len(self.starts) * 20,
                    width=report["width"],
                    height=report["height"],
                )
                report["output_sha256"] = hashlib.sha256(base.with_suffix(".mp4").read_bytes()).hexdigest()
                base.with_suffix(".json").write_text(json.dumps(report))
                return result
            assert (method, path) == ("POST", "/v1/runs/media-compose")
            assert payload["managed_runtime"] == runtime and payload["fps"] == 15
            rid = payload["run_id"]
            output = root / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            # The native process/environment is explicitly fake here; the CPU codec is real.
            compose(
                {
                    "root": str(root),
                    "output": str(output),
                    "request": {k: v for k, v in payload.items() if k != "managed_runtime"},
                }
            )
            self.records[rid] = {
                "run_id": rid,
                "executor": "media_compose",
                "pid": 4321,
                "process_group_id": 4321,
                "runner_id": "fake",
                "started_at": time.time(),
                "deadline_at": payload["deadline_at"],
                "alive": False,
                "status": "exited",
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "stdout_more": False,
                "stderr_more": False,
                "stdout_offset": 0,
                "stderr_offset": 0,
            }
            return self.records[rid]

    fake = Native()
    monkeypatch.setattr(EXECUTORS[NAME], "runner", lambda _: fake)
    monkeypatch.setattr(EXECUTORS["media_compose"], "runner", lambda _: fake)
    root = get_settings().data_dir
    source = root / "source.png"
    Image.new("RGB", (64, 64), "navy").save(source)
    with session_factory()() as session:
        image = register_file(
            session,
            source=source,
            artifact_type="image",
            mime_type="image/png",
            original_filename="boat.png",
            run_id=None,
        )
        session.commit()
        identity = image.id
    return SimpleNamespace(fake=fake, profile=profile, source=identity)


def work():
    with session_factory()() as session:
        return tick(session, "svi-film-worker")


def selected(task):
    with session_factory()() as session:
        return dict(session.get(Task, task).metadata_json["media_plan"])


def test_public_short_route_uses_shared_recurrent_adapter_and_fixed_recipe(bridge):
    request = body(bridge.source)
    request.pop("duration_seconds")
    request.pop("client_request_id")
    request["frames"] = 81
    with TestClient(app) as api:
        created = api.post("/api/video/runs", json=request)
        assert created.status_code == 202, created.text
        assert created.json()["executor_type"] == NAME
        assert created.json()["requested_resources"] == {"ram_mib": RAM_MIB}
        assert work() == created.json()["id"]
        assert api.get("/api/runs/" + created.json()["id"]).json()["status"] == "succeeded"


def test_public_ten_second_job_freezes_full_windows_and_composes_exact_timing(bridge):
    with TestClient(app) as api:
        request = body(bridge.source)
        created = api.post("/api/media/jobs/video", json=request)
        assert created.status_code == 202, created.text
        tid = created.json()["task_id"]
        plan = selected(tid)
        assert api.post("/api/media/jobs/video", json=request).json()["task_id"] == tid
        assert plan["timing"]["fps"] == 15 and plan["timing"]["target_frames"] == 150
        assert [s["first_frame"] for s in plan["timing"]["segments"]] == [0, 4]
        assert [s["generated_frames"] for s in plan["timing"]["segments"]] == [81, 81]
        with session_factory()() as session:
            runs = [session.get(Run, rid) for rid in plan["segment_run_ids"]]
            assert all(
                run.executor_type == NAME and run.parameters["image_artifact_id"] == bridge.source
                for run in runs
            )
            assert runs[1].parameters["previous_motion_run_id"] == runs[0].id
            assert all(run.requested_resources == {"ram_mib": RAM_MIB} for run in runs)
        assert work() == plan["segment_run_ids"][0]
        assert work() == plan["segment_run_ids"][1]
        assert work() == plan["compose_run_id"]
        result = api.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded", result
        with session_factory()() as session:
            artifact = session.get(Artifact, result["final_artifact_id"])
            assert artifact.metadata_json["frames"] == 150 and artifact.metadata_json["fps"] == 15
            assert not active_locks(session)
            with av.open(str(get_settings().data_dir / artifact.relative_path)) as movie:
                frames = list(movie.decode(video=0))
                assert len(frames) == 150 and float(frames[-1].time) == pytest.approx(149 / 15)
        assert bridge.fake.starts[0]["image"] == bridge.fake.starts[1]["image"]
        assert (
            bridge.fake.starts[0]["previous_motion"] is None
            and bridge.fake.starts[1]["previous_motion"] is not None
        )


def test_explicit_scenes_continue_within_each_scene_and_reset_at_the_cut(bridge):
    with TestClient(app) as api:
        created = api.post(
            "/api/media/jobs/video",
            json=body(
                bridge.source,
                duration_seconds=14,
                composition_mode="shots",
                scenes=[
                    {"prompt": "Opening pond", "duration_seconds": 6},
                    {"prompt": "Closing river", "duration_seconds": 8},
                ],
            ),
        )
        assert created.status_code == 202, created.text
        plan = selected(created.json()["task_id"])
        assert [x["first_frame"] for x in plan["timing"]["segments"]] == [0, 4, 0, 4]
        assert [x["output_frames"] for x in plan["timing"]["segments"]] == [81, 9, 81, 39]
        with session_factory()() as session:
            runs = [session.get(Run, rid) for rid in plan["segment_run_ids"]]
            assert [x.parameters["scene_index"] for x in runs] == [0, 0, 1, 1]
            assert [x.parameters.get("previous_motion_run_id") for x in runs] == [
                None,
                runs[0].id,
                None,
                runs[2].id,
            ]
        for _ in range(5):
            assert work()
        assert [x["previous_motion"] is None for x in bridge.fake.starts] == [True, False, True, False]


@pytest.mark.parametrize("lost", ["video", "checkpoint", "checkpoint_file"])
def test_resume_rebinds_rebuilt_scene_chain_and_retains_independent_completed_scenes(bridge, lost):
    with TestClient(app) as api:
        created = api.post(
            "/api/media/jobs/video",
            json=body(
                bridge.source,
                duration_seconds=14,
                composition_mode="shots",
                scenes=[
                    {"prompt": "Opening pond", "duration_seconds": 6},
                    {"prompt": "Closing river", "duration_seconds": 8},
                ],
            ),
        )
        assert created.status_code == 202, created.text
        tid = created.json()["task_id"]
        before = selected(tid)
        for _ in range(4):
            assert work()
        assert api.post("/api/media/jobs/" + tid + "/cancel", json={}).status_code == 200
        with session_factory()() as session:
            image = session.scalar(
                select(Artifact).where(
                    Artifact.run_id == before["segment_run_ids"][0], Artifact.artifact_type == "video"
                )
            )
            if lost == "video":
                image.trashed_at = utcnow()
            else:
                motion = session.get(Artifact, image.metadata_json["motion_context_artifact_id"])
                if lost == "checkpoint":
                    motion.trashed_at = utcnow()
                else:
                    (get_settings().data_dir / motion.relative_path).unlink()
            session.commit()
        resumed = api.post(
            "/api/media/jobs/" + tid + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        assert resumed.status_code == 202, resumed.text
        after = selected(tid)
        assert after["segment_run_ids"][:2] != before["segment_run_ids"][:2]
        assert after["segment_run_ids"][2:] == before["segment_run_ids"][2:]
        with session_factory()() as session:
            second = session.get(Run, after["segment_run_ids"][1])
            assert second.parameters["previous_motion_run_id"] == after["segment_run_ids"][0]
            assert "previous_motion" not in second.parameters
            assert "previous_motion_artifact_id" not in second.parameters
            assert second.parameters["parent_artifact_ids"] == [bridge.source]
        for _ in range(3):
            assert work()
        result = api.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded", result


def test_reviewed_agent_budget_is_not_extended_for_recurrent_generation(bridge):
    from app.media_jobs import LongVideoRequest, publish_video

    with session_factory()() as session:
        request = LongVideoRequest.model_validate(body(bridge.source))
        deadline = (utcnow() + timedelta(hours=2)).isoformat()
        result = publish_video(
            session,
            request,
            observed_profile=bridge.profile,
            execution_deadline_at=deadline,
            _prepare_translation=False,
        )
        plan = session.get(Task, result["task_id"]).metadata_json["media_plan"]
        assert plan["execution_deadline_at"] == deadline
        assert all(
            session.get(Run, rid).parameters["execution_deadline_at"] == deadline
            for rid in [*plan["segment_run_ids"], plan["compose_run_id"]]
        )


def test_recurrent_prompt_preparation_binds_original_inputs_and_ignores_derived_motion_lineage():
    from app.media_translation import image_fields, source_hash

    run = SimpleNamespace(
        executor_type=NAME,
        requested_gpu="auto",
        parameters={
            **GEOMETRY,
            "prompt": "A paper boat turns",
            "negative_prompt": "camera shake",
            "image_artifact_id": "source",
            "image": {"relative_path": "artifacts/source.png", "sha256": "a" * 64, "size_bytes": 10},
            "managed_runtime": {"profile": PROFILE, "manifest_sha256": "a" * 64, "environment_id": "b" * 64},
            "parent_artifact_ids": ["source"],
        },
    )
    fields = image_fields(run)
    assert fields == {"prompt": "A paper boat turns", "negative_prompt": "camera shake"}
    original = source_hash(run, fields)
    run.parameters.update(
        previous_motion={
            "relative_path": "artifacts/motion.safetensors",
            "sha256": "c" * 64,
            "size_bytes": 20,
        },
        previous_motion_artifact_id="motion",
        svi_profile_identity="d" * 64,
        parent_artifact_ids=["source", "motion"],
    )
    assert source_hash(run, fields) == original
    run.parameters["image"] = {**run.parameters["image"], "sha256": "e" * 64}
    assert source_hash(run, fields) != original


def test_short_recurrent_video_is_an_inspected_timeline_source_at_native_fps(bridge):
    with TestClient(app) as api:
        request = body(bridge.source)
        request.pop("duration_seconds")
        request.pop("client_request_id")
        request["frames"] = 81
        created = api.post("/api/video/runs", json=request)
        assert created.status_code == 202, created.text
        assert work()
        with session_factory()() as session:
            artifact = session.scalar(
                select(Artifact).where(
                    Artifact.run_id == created.json()["id"], Artifact.artifact_type == "video"
                )
            )
            identity = artifact.id
        source = api.get("/api/timelines/sources/" + identity)
        assert source.status_code == 200, source.text
        assert source.json()["fps"] == 15 and source.json()["frames"] == 81


def test_recurrent_prompt_preparation_is_shared_reviewed_and_survives_motion_binding(bridge, monkeypatch):
    from app.media_translation_text import digest
    from test_media_translation import settings

    calls = []

    async def complete(session, params):
        calls.append(params)
        assert "tools" not in params
        fields = json.loads(params["messages"][-1]["content"])
        yield json.dumps({key: value + ", gentle continuous motion" for key, value in fields.items()})

    monkeypatch.setattr("app.media_translation.completion_stream", complete)
    with TestClient(app) as api:
        settings(api, enabled=False)
        created = api.post(
            "/api/media/jobs/video",
            json=body(bridge.source, translation={"mode": "off", "enhance": True, "review": True}),
        )
        assert created.status_code == 202, created.text
        plan = selected(created.json()["task_id"])
        assert work()
        first = api.get("/api/runs/" + plan["segment_run_ids"][0]).json()
        receipt = first["metadata"]["prompt_translation"]
        assert receipt["policy"]["enhancement_template"].endswith(":svi-pro")
        review = api.get("/api/runs/" + receipt["review_run_id"]).json()
        assert len(calls) == 1 and work() is None and not bridge.fake.starts
        accepted = {**review["parameters"]["effective"], "prompt": "A boat circles the pond slowly"}
        response = api.post(
            "/api/generation/translations/" + review["id"] + "/review",
            json={"expected_hash": digest(review["parameters"]["effective"]), "effective": accepted},
        )
        assert response.status_code == 200, response.text
        while work():
            pass
        result = api.get("/api/media/jobs/" + created.json()["task_id"]).json()
        assert result["status"] == "succeeded", result
        assert len(calls) == 1
        assert all(call["prompt"] == accepted["prompt"] for call in bridge.fake.starts)


@pytest.mark.parametrize("bridge", ["landscape", "portrait"], indirect=True)
def test_selected_recurrent_agent_completes_through_shared_job_without_changing_its_budget(
    bridge, monkeypatch
):
    from test_agent_media import create, start

    identity = str(uuid4())
    profile = {
        **bridge.profile,
        "video_model": {
            "definition_id": identity,
            "binding": {"managed_runtime": bridge.profile["managed_runtime"]},
        },
    }
    monkeypatch.setattr("app.video_models.profile_for", lambda *args, **kwargs: profile)
    with TestClient(app) as api:
        request = body(
            bridge.source,
            model_id=identity,
            width=profile["width"],
            height=profile["height"],
        )
        request.pop("client_request_id")
        agent = create(api, kind="video", request=request, maximum_runtime=14400)
        root = start(api, agent)
        for _ in range(12):
            if work() is None:
                break
        result = api.get("/api/media/jobs/" + root["task_id"]).json()
        assert result["status"] == "succeeded", result
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.error_message) for r in runs
            ]
            video = [r for r in runs if r.executor_type == NAME]
            assert len(video) == 2 and all(r.agent_id == agent["id"] for r in video)
            assert len({r.parameters["execution_deadline_at"] for r in video}) == 1
            assert all(r.parameters["video_model"] == profile["video_model"] for r in video)
            assert all(
                (r.parameters["width"], r.parameters["height"]) == (profile["width"], profile["height"])
                for r in video
            )
            assert not active_locks(session)


@pytest.mark.parametrize("aspect,reference", [("landscape", True), ("portrait", True), ("landscape", False)])
def test_studio_shot_uses_model_recipe_and_refuses_missing_anchor_or_unsupported_portrait(
    bridge, monkeypatch, aspect, reference
):
    from app.video_models import recurrent_recipe
    from test_studio_materials import board, material
    from test_studio_shots import submit

    profile = {**bridge.profile, "operation_recipe": recurrent_recipe()}
    monkeypatch.setattr("app.video_models.profile_for", lambda *args, **kwargs: profile)
    with TestClient(app) as api:
        row = material(api, options={"audio": "silent", "aspect": aspect})
        storyboard = board("silent")
        storyboard["scenes"][0]["reference_artifact_ids"] = [bridge.source] if reference else []
        response = api.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": storyboard},
        )
        assert response.status_code == 201, response.text
        generated = submit(api, row, response.json())
        if aspect == "portrait" or not reference:
            assert generated.status_code == 422, generated.text
            with session_factory()() as session:
                assert not session.scalar(select(Run.id).where(Run.executor_type == NAME))
        else:
            assert generated.status_code == 202, generated.text
            with session_factory()() as session:
                parts = list(
                    session.scalars(
                        select(Run).where(
                            Run.task_id == generated.json()["task_id"], Run.executor_type == NAME
                        )
                    )
                )
                assert parts and all(
                    r.parameters["width"] == 832 and r.parameters["height"] == 480 for r in parts
                )
                assert all(r.parameters["image_artifact_id"] == bridge.source for r in parts)


@pytest.mark.parametrize("bridge", ["portrait"], indirect=True)
def test_studio_portrait_requests_the_admitted_profile_and_preserves_film_geometry(bridge, monkeypatch):
    from app.video_models import recurrent_recipe
    from test_studio_materials import board, material
    from test_studio_shots import submit

    calls = []

    def profile_for(*args, **kwargs):
        calls.append(kwargs.get("requested_geometry"))
        return {**bridge.profile, "operation_recipe": recurrent_recipe(bridge.profile)}

    monkeypatch.setattr("app.video_models.profile_for", profile_for)
    with TestClient(app) as api:
        row = material(api, options={"audio": "silent", "aspect": "portrait"})
        storyboard = board("silent")
        storyboard["scenes"][0]["reference_artifact_ids"] = [bridge.source]
        saved = api.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": storyboard},
        )
        assert saved.status_code == 201, saved.text
        result = submit(api, row, saved.json())
        assert result.status_code == 202, result.text
        assert calls and all(value == (480, 832) for value in calls)
        with session_factory()() as session:
            parts = list(
                session.scalars(
                    select(Run).where(
                        Run.task_id == result.json()["task_id"],
                        Run.executor_type == NAME,
                    )
                )
            )
            assert parts and all(
                (r.parameters["width"], r.parameters["height"]) == (480, 832)
                and r.parameters["image_artifact_id"] == bridge.source
                for r in parts
            )


@pytest.mark.parametrize("bridge", ["portrait"], indirect=True)
@pytest.mark.parametrize("long", [False, True])
def test_qualified_portrait_public_request_keeps_native_geometry_and_exact_film_timing(bridge, long):
    with TestClient(app) as api:
        request = body(bridge.source, width=480, height=832)
        if not long:
            request.pop("duration_seconds")
            request.pop("client_request_id")
            request["frames"] = 81
        created = api.post("/api/media/jobs/video" if long else "/api/video/runs", json=request)
        assert created.status_code == 202, created.text
        for _ in range(3 if long else 1):
            assert work()
        if long:
            result = api.get("/api/media/jobs/" + created.json()["task_id"]).json()
            assert result["status"] == "succeeded", result
            with session_factory()() as db:
                artifact = db.get(Artifact, result["final_artifact_id"])
                relative = artifact.relative_path
                metadata = artifact.metadata_json
        else:
            result = api.get("/api/runs/" + created.json()["id"]).json()
            assert result["status"] == "succeeded", result
            with session_factory()() as db:
                artifact = db.scalar(
                    select(Artifact).where(
                        Artifact.run_id == created.json()["id"], Artifact.artifact_type == "video"
                    )
                )
                relative = artifact.relative_path
                metadata = artifact.metadata_json
        assert (metadata["width"], metadata["height"], metadata["fps"]) == (480, 832, 15)
        with av.open(str(get_settings().data_dir / relative)) as film:
            frames = list(film.decode(video=0))
            assert len(frames) == (150 if long else 81)
            assert all((frame.width, frame.height) == (480, 832) for frame in frames)
            assert float(frames[-1].time) == pytest.approx((len(frames) - 1) / 15)
        assert all(start["generation_profile"] == "portrait" for start in bridge.fake.starts)
        if long:
            assert bridge.fake.starts[1]["previous_motion"] is not None
