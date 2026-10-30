"""Current-turn sound intent through existing queue/native contracts; fake inference."""

import pytest
from app import assistant
from app.api import app
from app.conversation_effects import requested
from app.db import control_session_factory
from app.engine import tick
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_music import conversation
from test_effects import sound_bridge as sound_bridge
from test_effects import source_video


@pytest.mark.parametrize(
    "text",
    [
        "Add sound to this film: rain in the trees",
        "Dodaj do tego filmu dźwięk deszczu",
        "Wygeneruj odgłosy do tego wideo: ptaki",
    ],
)
def test_referential_sound_intent(text):
    assert requested({"action": "auto", "content": text})


@pytest.mark.parametrize(
    "text",
    [
        "How do I add sound to this film?",
        "Create an agent that adds sound to this video",
        "Create a prompt for sound effects for this film",
        "Do not add sound to this film",
        '"Add sound to this film"',
    ],
)
def test_questions_drafts_and_quoted_text_do_not_request_sound(text):
    assert not requested({"action": "auto", "content": text})


def drain():
    for _ in range(32):
        with control_session_factory()() as db:
            if tick(db, "conversation-sound-test") is None:
                return
    raise AssertionError("Sound task did not drain")


@pytest.mark.parametrize("mode", ["chat", "work", "assistant"])
def test_explicit_film_selection_needs_no_provider_and_keeps_stem_and_preview(
    sound_bridge, monkeypatch, mode
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Direct effects attempted text inference")

    monkeypatch.setattr(assistant, "completion_stream", forbidden)
    with TestClient(app) as api:
        source = source_video(api)
        cid = conversation(api, mode)
        result = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Rain on the leaves",
                "action": "audio.effects",
                "effects": {"video_artifact_id": source, "preview_mode": "replace"},
                "web_search": {"enabled": True},
                "reasoning": {"enabled": True, "budget": 256},
            },
        )
        assert result.status_code == 202, result.text
        identity = result.json()["id"]
        drain()
        with control_session_factory()() as db:
            root = db.get(Run, identity)
            assert root.status == "succeeded", root.error_message
            assert root.parameters["web_search"]["enabled"] is False and root.parameters["reasoning"] is None
            outputs = list(db.scalars(select(Run).where(Run.task_id == root.task_id)))
            assert all(r.status == "succeeded" for r in outputs), [
                (r.executor_type, r.error_message) for r in outputs
            ]
            assert {r.executor_type for r in outputs} == {
                "orchestrator",
                "mmaudio_effects",
                "effects_preview",
            }
            stem = next(r for r in outputs if r.executor_type == "mmaudio_effects")
            assert (
                stem.parameters["prompt"] == "Rain on the leaves"
                and stem.parameters["video_artifact_id"] == source
            )
        messages = api.get(f"/api/chat/conversations/{cid}").json()["messages"]
        assistant_message = next(m for m in messages if m["role"] == "assistant")
        assert {a["type"] for a in assistant_message["artifacts"]} == {"audio", "video"}


@pytest.fixture
def mix_bridge(sound_bridge, monkeypatch):
    """Existing fake native journal plus typed CPU timeline publication (no real scope)."""
    import sys

    from ai_station_runner import timeline_runtime
    from app.config import get_settings

    root = get_settings().data_dir
    script = root / "synthetic-timeline.py"
    script.write_text("""import json,sys
from pathlib import Path
body=json.loads(Path(sys.argv[1]).read_text())['request'];rid=body['run_id'];m=body['manifest'];root=Path.cwd()
out=root/'artifacts'/rid[:2]/rid[2:4]/(rid+'.mp4');out.parent.mkdir(parents=True,exist_ok=True)
frames=max([c['start_frame']+((c['out_frame']-c['in_frame'])*m['fps']+next(s['fps'] for s in body['sources'] if s['artifact_id']==c['artifact_id'])-1)//next(s['fps'] for s in body['sources'] if s['artifact_id']==c['artifact_id']) for c in m['clips']]+[t['start_frame']+t['duration_frames'] for t in m['tracks']])
out.write_bytes(b'synthetic mixed film')
out.with_suffix('.json').write_text(json.dumps({'verified':True,'frames':frames,'fps':m['fps'],'width':m['width'],'height':m['height'],'timeline_audio_samples':frames*48000//m['fps'],'timeline_audio_rate':48000,'source_ids':sorted(s['artifact_id'] for s in body['sources']),'observation':body['observation']}))
""")
    monkeypatch.setattr(
        timeline_runtime, "scope_prefix", lambda rid, ram: ["/fixed-timeline-scope", str(ram)]
    )
    monkeypatch.setattr(timeline_runtime, "installation", lambda: __import__("pathlib").Path(sys.executable))
    monkeypatch.setattr(
        "app.timelines.capabilities",
        lambda: {"available": True, "ram_mib": 4096, "observation": timeline_runtime.observation()},
    )
    manager = sound_bridge["manager"]
    original = manager.start

    def launch(**kwargs):
        if kwargs["executor"] == "timeline_render":
            assert kwargs["argv"][:2] == ["/fixed-timeline-scope", "4096"]
            kwargs = {**kwargs, "argv": [sys.executable, str(script), kwargs["argv"][-1]]}
            from ai_station_runner.processes import ProcessManager

            return ProcessManager.start(manager, **kwargs)
        return original(**kwargs)

    monkeypatch.setattr(manager, "start", launch)
    return sound_bridge


def test_default_sound_mix_is_an_owned_reopenable_timeline_with_exact_source_stem_and_gains(mix_bridge):
    from app.models import CreativeSession, TimelineRevision

    with TestClient(app) as api:
        source = source_video(api)
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Wind in trees",
                "action": "audio.effects",
                "effects": {"video_artifact_id": source, "original_gain": 0.8, "effects_gain": 0.4},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        with control_session_factory()() as db:
            parent = db.get(Run, response.json()["id"])
            runs = list(db.scalars(select(Run).where(Run.task_id == parent.task_id)))
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.error_message) for r in runs
            ]
            stem = next(r for r in runs if r.executor_type == "mmaudio_effects")
            preview = next(r for r in runs if r.executor_type == "timeline_render")
            workspace = db.get(CreativeSession, stem.metadata_json["effects_edit_session_id"])
            revision = db.get(TimelineRevision, preview.parameters["revision_id"])
            assert revision.session_id == workspace.id and workspace.capability == "timeline"
            assert (
                revision.manifest["clips"][0]["artifact_id"] == source
                and revision.manifest["clips"][0]["gain"] == 0.8
            )
            assert revision.manifest["tracks"][0]["gain"] == 0.4
            assert workspace.draft["formState"]["preview_run_id"] == preview.id
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "succeeded" and len(message["sound_edits"]) == 1
        assert {a["type"] for a in message["artifacts"]} == {"audio", "video"}


@pytest.fixture
def film_bridge(mix_bridge, monkeypatch):
    from app import video
    from app.artifacts import register_file
    from app.config import get_settings
    from app.executors import EXECUTORS
    from app.runs import transition
    from app.state import RunStatus

    monkeypatch.setattr(
        video,
        "capabilities",
        lambda: {"available": True, "memory_estimate_mib": 16384, "profile_observation": "b" * 64},
    )

    class SyntheticFilm:
        def execute(self, session, run):
            for status in (RunStatus.PREPARING, RunStatus.RUNNING):
                transition(session, run, status, event_type="synthetic")
            is_compose = run.executor_type == "media_compose"
            params = run.parameters
            source = get_settings().data_dir / (run.id + ".mp4")
            source.write_bytes(b"synthetic generated movie")
            a = register_file(
                session,
                source=source,
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="film.mp4",
                run_id=run.id,
                metadata={
                    "frames": params["timeline"]["target_frames"] if is_compose else params["frames"],
                    "fps": 24,
                    "width": params["width"],
                    "height": params["height"],
                    **({"internal_media": True} if params.get("internal_media") else {}),
                },
            )
            if is_compose:
                run.task.metadata_json = {
                    **run.task.metadata_json,
                    "media_plan": {**run.task.metadata_json["media_plan"], "final_artifact_id": a.id},
                }
            transition(session, run, RunStatus.SUCCEEDED, event_type="synthetic")
            return "done"

    monkeypatch.setitem(EXECUTORS, "wan_video", SyntheticFilm())
    monkeypatch.setitem(EXECUTORS, "media_compose", SyntheticFilm())
    return mix_bridge


@pytest.mark.parametrize("duration", [None, 15])
def test_new_film_then_sound_have_real_dependencies_and_do_not_show_silent_intermediate_as_final(
    film_bridge, duration
):
    from app.models import RunDependency

    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        body = {
            "content": "Generate a film of rain in a forest",
            "action": "video.generate",
            "effects": {"prompt": "Rain on the leaves"},
        }
        if duration:
            body["media"] = {"duration_seconds": duration, "composition_mode": "continuous"}
        result = api.post(f"/api/chat/conversations/{cid}/messages", json=body)
        assert result.status_code == 202, result.text
        with control_session_factory()() as db:
            root = db.get(Run, result.json()["id"])
            assert tick(db, "film-test") == root.id
            prep = db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type == "film_sound_prepare")
            )
            assert prep is not None, root.error_message
            assert (
                db.scalar(select(RunDependency).where(RunDependency.run_id == prep.id)).prerequisite_id
                == prep.parameters["source_run_id"]
            )
            assert not db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type == "mmaudio_effects")
            )
        # Run only the film producers, pausing before sound preparation.
        for _ in range(24):
            with control_session_factory()() as db:
                source = db.get(Run, prep.parameters["source_run_id"])
                if source.status == "succeeded":
                    break
                assert tick(db, "film-test") is not None
        else:
            pytest.fail("Film did not complete")
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] != "succeeded"
        assert not any(a["type"] == "video" for a in message["artifacts"])
        if duration:
            assert message["media_job"]["final_artifact_id"] is None
            assert message["media_job"]["soundtrack_status"] == "waiting_for_film"
        drain()
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "succeeded", message
        assert {a["type"] for a in message["artifacts"]} == {"audio", "video"}
        assert len(message["sound_edits"]) == 1
        if duration:
            assert message["media_job"]["final_artifact_id"] in [a["id"] for a in message["artifacts"]]
        with control_session_factory()() as db:
            child = db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type == "mmaudio_effects")
            )
            assert child.parameters["prompt"] == "Rain on the leaves"
            assert child.parent_run_id == prep.id


@pytest.mark.parametrize(
    "text",
    [
        "Generate a 5 second video of rain with sound: rain on leaves",
        "Wygeneruj 5 sekund filmu lasu z dźwiękiem: ptaki",
    ],
)
def test_natural_new_film_sound_runs_without_text_inference(film_bridge, monkeypatch, text):
    def forbidden(*args, **kwargs):
        pytest.fail("Explicit new film+sound must not call a text provider")

    monkeypatch.setattr(assistant, "completion_stream", forbidden)
    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(f"/api/chat/conversations/{cid}/messages", json={"content": text})
        assert response.status_code == 202, response.text
        drain()
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "succeeded", message


def test_automatic_film_followup_binds_verified_mix_and_rejects_latest_unfinished(film_bridge):
    from app.models import Artifact

    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        route = f"/api/chat/conversations/{cid}"
        first = api.post(route + "/messages", json={"content": "Generate a film with sound: rain"})
        assert first.status_code == 202, first.text
        drain()
        message = api.get(route).json()["messages"][-1]
        film = next(a["id"] for a in message["artifacts"] if a["type"] == "video")
        followup = api.post(route + "/messages", json={"content": "Add sound to this film: birds"})
        assert followup.status_code == 202, followup.text
        with control_session_factory()() as db:
            root = db.get(Run, followup.json()["id"])
            assert root.parameters["effects"]["video_artifact_id"] == film
            assert root.parameters["effects_video"]["sha256"] == db.get(Artifact, film).sha256
        drain()
        pending = api.post(route + "/messages", json={"content": "Generate a film with sound: thunder"})
        assert pending.status_code == 202, pending.text
        with control_session_factory()() as db:
            tick(db, "film-test")
        denied = api.post(route + "/messages", json={"content": "Add sound to this film: birds"})
        assert denied.status_code == 409, denied.text
        from app.conversation_effects import visible_film
        from app.models import Conversation
        from fastapi import HTTPException

        with control_session_factory()() as db:
            with pytest.raises(HTTPException, match="still receiving"):
                visible_film(db, db.get(Conversation, cid))


def test_film_sound_stop_before_source_completion_prevents_late_sound_publication(film_bridge):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Generate a film with sound: rain"}
        )
        with control_session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            assert tick(db, "film-test") == root.id
            db.refresh(root)
            cancel_task(db, root.task)
            db.commit()
        drain()
        with control_session_factory()() as db:
            runs = list(db.scalars(select(Run).where(Run.task_id == root.task_id)))
            assert not any(r.executor_type == "mmaudio_effects" for r in runs)
            assert all(r.status in {"succeeded", "canceled"} for r in runs)


def test_changed_existing_film_bytes_fail_before_native_effects_dispatch(mix_bridge):
    from app.config import get_settings
    from app.models import Artifact

    with TestClient(app) as api:
        source = source_video(api)
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Rain", "action": "audio.effects", "effects": {"video_artifact_id": source}},
        )
        assert response.status_code == 202, response.text
        with control_session_factory()() as db:
            original = db.get(Artifact, source)
            path = get_settings().data_dir / original.relative_path
            path.write_bytes(b"x" * path.stat().st_size)
        drain()
        assert not mix_bridge["launches"]
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "failed"


def test_sound_coordinator_receipt_reopens_without_a_second_dependency_graph(film_bridge):
    from app.film_sound import enqueue

    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Generate a film with sound: rain"}
        )
        with control_session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            tick(db, "film-test")
            prep = db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type == "film_sound_prepare")
            )
            again = enqueue(
                db,
                root,
                prep.parameters["source_run_id"],
                prep.parameters["profile"],
                prep.parameters["renderer"],
            )
            assert again.id == prep.id
            assert (
                len(
                    list(
                        db.scalars(
                            select(Run).where(
                                Run.task_id == root.task_id, Run.executor_type == "film_sound_prepare"
                            )
                        )
                    )
                )
                == 1
            )


@pytest.mark.parametrize("failure_stage", ["prepare", "mix"])
def test_resume_failed_sound_reuses_completed_film_and_receipt_without_regenerating_video(
    film_bridge, monkeypatch, failure_stage
):
    from uuid import uuid4

    from app.film_sound import FilmSoundExecutor
    from app.timelines import TimelineExecutor

    executor = FilmSoundExecutor if failure_stage == "prepare" else TimelineExecutor
    execute = executor.execute
    failed = []

    def fail_once(self, session, run):
        if not failed:
            failed.append(run.id)
            raise ValueError("Synthetic sound preparation failure")
        return execute(self, session, run)

    monkeypatch.setattr(executor, "execute", fail_once)
    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        route = f"/api/chat/conversations/{cid}"
        response = api.post(
            route + "/messages",
            json={
                "content": "Generate a film of rain",
                "action": "video.generate",
                "media": {"duration_seconds": 15, "composition_mode": "continuous"},
                "effects": {"prompt": "Rain"},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        message = api.get(route).json()["messages"][-1]
        job = message["media_job"]
        assert job["status"] == "failed" and job["resume_allowed"]
        with control_session_factory()() as db:
            before = list(
                db.scalars(
                    select(Run.id).where(
                        Run.task_id == job["task_id"], Run.executor_type.in_(["wan_video", "media_compose"])
                    )
                )
            )
        body = {"client_request_id": str(uuid4()), "expected_revision": job["revision"]}
        resume = api.post(f"/api/media/jobs/{job['task_id']}/resume", json=body)
        assert resume.status_code == 202, resume.text
        assert api.post(f"/api/media/jobs/{job['task_id']}/resume", json=body).json() == resume.json()
        drain()
        latest = api.get(route).json()["messages"][-1]
        job = latest["media_job"]
        assert job["status"] == "succeeded", job
        assert len(latest["sound_edits"]) == 1 and len(latest["sound_runs"]) == 1
        with control_session_factory()() as db:
            after = list(
                db.scalars(
                    select(Run.id).where(
                        Run.task_id == job["task_id"], Run.executor_type.in_(["wan_video", "media_compose"])
                    )
                )
            )
            assert before == after


@pytest.mark.parametrize(
    "extra",
    [
        {"video_artifact_id": "0bf4d4cf-4daa-4c76-9166-3be6f11111fc", "prompt": "Rain"},
        {"prompt": ""},
        {"prompt": "Rain", "original_gain": True},
        {"prompt": "Rain", "cues": [{"start_frame": 1, "end_frame": 0, "prompt": "Rain"}]},
    ],
)
def test_new_film_sound_rejects_invalid_or_injected_scope_before_work(film_bridge, extra):
    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Generate a film", "action": "video.generate", "effects": extra},
        )
        assert response.status_code == 422, response.text
        with control_session_factory()() as db:
            assert not list(db.scalars(select(Run).where(Run.conversation_id == cid)))


def test_sound_cues_are_rechecked_against_generated_film_before_gpu_dispatch(film_bridge):
    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Generate a film",
                "action": "video.generate",
                "effects": {
                    "prompt": "Rain",
                    "cues": [{"start_frame": 0, "end_frame": 7200, "prompt": "Rain"}],
                },
            },
        )
        assert response.status_code == 202, response.text
        drain()
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "failed"
        assert not film_bridge["launches"]


def test_mix_publication_reconciles_same_child_workspace_revision_and_history_turn(mix_bridge):
    from app.effects_mix import publish
    from app.models import Artifact, CreativeSession, CreativeTurn, TimelineRevision

    with TestClient(app) as api:
        source = source_video(api)
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Rain", "action": "audio.effects", "effects": {"video_artifact_id": source}},
        )
        assert response.status_code == 202, response.text
        drain()
        with control_session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            stem = db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type == "mmaudio_effects")
            )
            artifact = db.scalar(
                select(Artifact).where(Artifact.run_id == stem.id, Artifact.artifact_type == "audio")
            )
            again = publish(db, stem, artifact)
            assert again.id == stem.metadata_json["effects_preview_run_id"]
            assert len(list(db.scalars(select(CreativeSession)))) == 1
            assert len(list(db.scalars(select(CreativeTurn)))) == 1
            assert len(list(db.scalars(select(TimelineRevision)))) == 1


def test_changed_admitted_effects_runtime_blocks_new_film_sound_before_gpu_work(film_bridge, monkeypatch):
    from app import effects

    with TestClient(app) as api:
        cid = conversation(api, "assistant")
        response = api.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Generate a film with sound: rain"}
        )
        assert response.status_code == 202, response.text
        for _ in range(2):
            with control_session_factory()() as db:
                tick(db, "film-test")
        admitted = effects.capabilities()
        monkeypatch.setattr(effects, "capabilities", lambda: {**admitted, "observation": "c" * 64})
        drain()
        assert not film_bridge["launches"]
        message = api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert message["task_status"] == "failed"
        assert any("runtime changed" in step["error_message"] for step in message["steps"])
