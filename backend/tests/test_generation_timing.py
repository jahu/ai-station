"""Private duration profiles and actual API/worker progress persistence."""

import os
from datetime import timedelta
from pathlib import Path

import pytest
from app.db import control_session_factory, reset_engine, utcnow
from app.engine import tick
from app.generation_progress import begin_timing, projection
from app.models import RunEvent
from app.runs import create_run, create_task
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_images import bridge as bridge

HARDWARE = {
    "gpus": [{"index": 7, "uuid": "synthetic-gpu", "name": "Synthetic GPU", "memory_total_mib": 12288}],
    "memory": {"total_mib": 32768},
}


def test_similar_job_estimates_are_owner_profile_and_success_bound(accounts):
    _, alice, bob = accounts
    owners = [client.get("/api/auth").json()["user"]["id"] for client in (alice, bob)]
    with control_session_factory()() as db:
        task = create_task(db, title="Synthetic timing", prompt="", capability="image.generate")
        task.owner_id = owners[0]
        current = create_run(
            db,
            task,
            run_type="image",
            capability="image.generate",
            executor_type="photo_pipe",
            parameters={"steps": 8, "backend": "qwen", "width": 768, "height": 1024},
        )
        current.owner_id = owners[0]
        current.actual_gpu = "7"
        current.allocated_resources = {"gpu": "7"}
        current.status = "running"
        current.started_at = utcnow() - timedelta(seconds=20)
        begin_timing(db, current, HARDWARE)
        profile = current.metadata_json["generation_timing"]["profile"]
        for owner, duration, status in [
            (owners[0], 100, "succeeded"),
            (owners[0], 110, "succeeded"),
            (owners[0], 120, "succeeded"),
            (owners[0], 9999, "failed"),
            (owners[1], 9999, "succeeded"),
        ]:
            prior_task = task
            if owner != task.owner_id:
                prior_task = create_task(db, title="Other owner", prompt="", capability="image.generate")
                prior_task.owner_id = owner
            prior = create_run(
                db, prior_task, run_type="image", capability="image.generate", executor_type="photo_pipe"
            )
            prior.owner_id = owner
            prior.status = status
            prior.started_at = utcnow() - timedelta(seconds=duration + 100)
            prior.finished_at = prior.started_at + timedelta(seconds=duration)
            prior.metadata_json = {"generation_timing": {"profile": profile}}
        db.commit()
        begin_timing(db, current, HARDWARE)
        timing = current.metadata_json["generation_timing"]
        assert timing["samples"] == 3 and timing["lower_seconds"] == 90 and timing["upper_seconds"] == 132
        value = projection(current)["estimate"]
        assert value["scope"] == "this stage" and value["samples"] == 3
        current.parameters = {**current.parameters, "steps": 30}
        begin_timing(db, current, HARDWARE)
        assert "samples" not in current.metadata_json["generation_timing"]
        # Recovery never recomputes a previously dispatched job's frozen profile.
        current.metadata_json = {**current.metadata_json, "dispatch_attempted": True}
        before = current.metadata_json["generation_timing"]
        current.parameters = {**current.parameters, "steps": 8}
        begin_timing(db, current, HARDWARE)
        assert current.metadata_json["generation_timing"] == before


@pytest.mark.parametrize("bad_output", [False, True])
def test_fake_native_image_progress_survives_restart_and_is_private(accounts, bridge, bad_output):
    _, alice, bob = accounts
    script = Path(os.environ["AI_STATION_PHOTO_SCRIPT"])
    script.write_text(
        script.read_text().replace(
            "print('diagnostic', file=sys.stderr)",
            "print('2/4 - 1.50s/it\\r4/4 - 1.50s/it', file=sys.stderr)",
        )
    )
    if bad_output:
        script.write_text(
            script.read_text().replace(
                "Image.new('RGB', (64,48), '#426c57').save(args[args.index('--out')+1])",
                "__import__('pathlib').Path(args[args.index('--out')+1]).write_bytes(b'not an image')",
            )
        )
    result = alice.post(
        "/api/images/runs",
        json={"mode": "t2i", "backend": "qwen", "prompt": "Synthetic landscape", "steps": 4, "gpu": "7"},
    )
    assert result.status_code == 202, result.text
    identity = result.json()["id"]
    with control_session_factory()() as db:
        assert tick(db, "synthetic-progress-worker") == identity
        events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == identity, RunEvent.event_type == "generation.progress"
                )
            )
        )
        assert events and events[-1].payload["phase"] == "finishing"
    reset_engine()
    view = alice.get("/api/runs/" + identity).json()
    expected = "failed" if bad_output else "succeeded"
    assert view["status"] == expected and view["generation_progress"]["phase"] == expected
    assert view["generation_progress"]["estimate"] is None
    assert "generation_progress_buffers" not in view["metadata"]
    assert bob.get("/api/runs/" + identity).status_code == 404
