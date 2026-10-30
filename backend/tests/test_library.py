import io
import wave
from uuid import uuid4

from app.api import app
from app.db import session_factory
from app.models import Artifact, Run
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select


def wav_bytes():
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    return result.getvalue()


def upload(client, filename="source.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, "PNG")
    response = client.post("/api/images/uploads", files={"file": (filename, buffer.getvalue(), "image/png")})
    assert response.status_code == 201
    return response.json()


def test_library_edit_trash_restore_preserves_media_and_rejects_stale_writes():
    with TestClient(app) as client:
        source = upload(client)
        path = f"/api/artifacts/{source['id']}"
        original = client.get(path + "/file").content
        edit = {"title": "My portrait", "notes": "For the avatar", "expected_updated_at": None}
        changed = client.patch(path, json=edit)
        assert changed.status_code == 200, changed.text
        artifact = changed.json()
        assert artifact["title"] == "My portrait"
        assert artifact["original_filename"] == source["original_filename"]
        assert artifact["metadata"] == source["metadata"]
        assert client.patch(path, json=edit).status_code == 409
        trash = client.request("DELETE", path, json={"expected_updated_at": artifact["library_updated_at"]})
        assert trash.status_code == 200
        assert client.get("/api/artifacts").json() == []
        assert client.get("/api/artifacts?view=trash").json()[0]["id"] == source["id"]
        assert client.get(path + "/file").content == original
        restored = client.post(
            path + "/restore", json={"expected_updated_at": trash.json()["library_updated_at"]}
        )
        assert restored.status_code == 200 and restored.json()["trashed_at"] is None
        assert client.get("/api/artifacts").json()[0]["title"] == "My portrait"
        assert client.patch(path, json={**edit, "relative_path": "../escape"}).status_code == 422


def test_trash_keeps_run_artifacts_lineage_and_audit_events():
    with TestClient(app) as client:
        source = upload(client)
        output = upload(client)
        with session_factory()() as session:
            run = create_run(
                session,
                create_task(session, title="Image", prompt="Image", capability="image.generate"),
                run_type="image",
                capability="image.generate",
                executor_type="photo_pipe",
            )
            row = session.get(Artifact, output["id"])
            row.run_id = run.id
            row.parent_artifact_ids = [source["id"]]
            session.commit()
            run_id = run.id
        response = client.request(
            "DELETE", f"/api/artifacts/{output['id']}", json={"expected_updated_at": None}
        )
        assert response.status_code == 200
        assert len(client.get("/api/artifacts").json()) == 1
        history = client.get("/api/artifacts", params={"run_id": run_id}).json()
        assert history[0]["parent_artifact_ids"] == [source["id"]]
        assert history[0]["trashed_at"] is not None
        events = client.get(f"/api/runs/{run_id}/events").json()
        assert events[-1]["event_type"] == "artifact.trashed"


def test_library_search_filters_and_pagination():
    with TestClient(app) as client:
        first = upload(client, "Portrait.png")
        second = upload(client, "100% complete.png")
        assert len(client.get("/api/artifacts", params={"kind": "audio"}).json()) == 0
        assert len(client.get("/api/artifacts", params={"kind": "image"}).json()) == 2
        assert client.get("/api/artifacts", params={"search": "%"}).json()[0]["id"] == second["id"]
        assert len(client.get("/api/artifacts", params={"search": "%"}).json()) == 1
        assert client.get("/api/artifacts", params={"search": "PORTRAIT"}).json()[0]["id"] == first["id"]
        one = client.get("/api/artifacts", params={"limit": 1}).json()
        two = client.get("/api/artifacts", params={"limit": 1, "offset": 1}).json()
        assert one[0]["id"] != two[0]["id"]
        assert client.get("/api/artifacts", params={"offset": -1}).status_code == 422


def test_library_migration_preserves_existing_artifacts(legacy_schema):
    from alembic import command
    from app.db import alembic_config

    with TestClient(app) as client:
        source = upload(client)
        legacy_schema("0004")
        command.upgrade(alembic_config(), "head")
        migrated = client.get(f"/api/artifacts/{source['id']}").json()
        assert migrated["metadata"] == source["metadata"]
        assert migrated["relative_path"] == source["relative_path"]
        assert migrated["title"] == migrated["notes"] == ""
        assert migrated["library_updated_at"] is migrated["trashed_at"] is None
        assert client.get(f"/api/artifacts/{source['id']}/file").status_code == 200


def test_shared_media_lineage_resolves_sources_and_derived_across_types():
    with TestClient(app) as client:
        portrait = upload(client, "portrait.png")
        voice = client.post("/api/audio/uploads", files={"file": ("voice.wav", wav_bytes(), "audio/wav")})
        assert voice.status_code == 201, voice.text
        voice = voice.json()
        edited = upload(client, "edited.png")
        with session_factory()() as session:
            session.get(Artifact, edited["id"]).parent_artifact_ids = [portrait["id"]]
            video = Artifact(
                artifact_type="video",
                mime_type="video/mp4",
                relative_path=f"artifacts/{uuid4().hex}.mp4",
                original_filename="avatar.mp4",
                parent_artifact_ids=[edited["id"], voice["id"]],
                metadata_json={"capability": "avatar.animate"},
            )
            session.add(video)
            session.commit()
            video_id = video.id
            run_count = session.scalar(select(func.count()).select_from(Run))
        client.request(
            "DELETE",
            f"/api/artifacts/{edited['id']}",
            json={"expected_updated_at": None},
        )
        missing = str(uuid4())
        with session_factory()() as session:
            session.get(Artifact, video_id).parent_artifact_ids = [
                edited["id"],
                voice["id"],
                missing,
            ]
            session.commit()

        video_lineage = client.get(f"/api/artifacts/{video_id}/lineage")
        assert video_lineage.status_code == 200, video_lineage.text
        assert video_lineage.json()["id"] == video_id
        assert [item["id"] for item in video_lineage.json()["sources"]] == [edited["id"], voice["id"]]
        assert video_lineage.json()["sources"][0]["trashed_at"] is not None
        assert video_lineage.json()["sources"][1]["type"] == "audio"
        assert video_lineage.json()["derived"] == []

        portrait_lineage = client.get(f"/api/artifacts/{portrait['id']}/lineage").json()
        assert portrait_lineage["sources"] == []
        assert [item["id"] for item in portrait_lineage["derived"]] == [edited["id"]]

        edited_lineage = client.get(f"/api/artifacts/{edited['id']}/lineage").json()
        assert [item["id"] for item in edited_lineage["sources"]] == [portrait["id"]]
        assert [item["id"] for item in edited_lineage["derived"]] == [video_id]

        voice_lineage = client.get(f"/api/artifacts/{voice['id']}/lineage").json()
        assert [item["id"] for item in voice_lineage["derived"]] == [video_id]

        later = upload(client, "later.png")
        with session_factory()() as session:
            row = session.get(Artifact, later["id"])
            row.parent_artifact_ids = [portrait["id"], portrait["id"], later["id"], ""]
            session.commit()
        later_lineage = client.get(f"/api/artifacts/{later['id']}/lineage").json()
        assert [item["id"] for item in later_lineage["sources"]] == [portrait["id"]]
        portrait_derived = [
            item["id"] for item in client.get(f"/api/artifacts/{portrait['id']}/lineage").json()["derived"]
        ]
        assert portrait_derived == [later["id"], edited["id"]]

        assert client.get(f"/api/artifacts/{uuid4()}/lineage").status_code == 404
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Run)) == run_count
