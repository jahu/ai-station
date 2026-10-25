"""Native photo outputs use their owned Run path, distinct from upload UUID paths."""

from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from app.paths import artifact_relative, safe_join
from app.vision_inputs import freeze, verify
from fastapi.testclient import TestClient
from test_images import bridge as bridge


def generated():
    with TestClient(app) as api:
        queued = api.post(
            "/api/images/runs",
            json={"mode": "t2i", "prompt": "A fixture image", "steps": 1, "width": 256, "height": 256},
        )
        assert queued.status_code == 202, queued.text
        with session_factory()() as db:
            tick(db, "generated-input-path")
        run = queued.json()
        assert api.get("/api/runs/" + run["id"]).json()["status"] == "succeeded"
        outputs = api.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(outputs) == 1
        return run["id"], outputs[0]["id"]


def test_completed_native_photo_is_a_verified_input_without_copying_or_renaming(bridge):
    rid, aid = generated()
    with session_factory()() as db:
        artifact = db.get(Artifact, aid)
        assert aid != rid and artifact.relative_path == artifact_relative(rid, ".png")
        verify(db, freeze(db, [aid]), read_bytes=True)
        assert artifact.relative_path == artifact_relative(rid, ".png")


@pytest.mark.parametrize(
    "problem", ["owner", "producer", "status", "dispatch", "cleanup", "capability", "path"]
)
def test_a_run_named_file_requires_its_exact_confirmed_photo_owner(bridge, problem):
    rid, aid = generated()
    with session_factory()() as db:
        artifact, source = db.get(Artifact, aid), db.get(Run, rid)
        if problem == "owner":
            artifact.run_id = None
        elif problem == "producer":
            source.executor_type = "other"
        elif problem == "status":
            source.status = "failed"
        elif problem == "dispatch":
            source.metadata_json = {**source.metadata_json, "dispatch_attempted": False}
        elif problem == "cleanup":
            source.metadata_json = {**source.metadata_json, "process_confirmed_gone": False}
        elif problem == "capability":
            artifact.metadata_json = {**artifact.metadata_json, "capability": "other"}
        else:
            original = safe_join(get_settings().data_dir, artifact.relative_path).read_bytes()
            artifact.relative_path = artifact_relative(str(uuid4()), ".png")
            path = safe_join(get_settings().data_dir, artifact.relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)
        db.flush()
        with pytest.raises(ValueError, match="storage path"):
            verify(db, freeze(db, [aid]), read_bytes=True)


def test_generated_input_still_requires_the_original_file_bytes(bridge):
    _, aid = generated()
    with session_factory()() as db:
        artifact = db.get(Artifact, aid)
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed")
        with pytest.raises(ValueError):
            verify(db, freeze(db, [aid]), read_bytes=True)
