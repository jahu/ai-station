"""Real file primitive + fake public HTTPS; no real model, GPU or SDK execution."""

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from app import bundle_setup
from app import model_download_files as files
from app.api import app
from app.config import get_settings
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.model_bundles import BUNDLES, Bundle, BundleFile
from app.models import Artifact, ModelDefinition, ModelFile, ResourceLock, Run, RunEvent
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select


def body(entry):
    return {
        "client_request_id": str(uuid4()),
        "catalog_id": entry.id,
        "manifest_sha256": bundle_setup.fingerprint(entry.model_dump(mode="json")),
        "license_accepted": True,
    }


def work():
    with control_session_factory()() as db:
        return tick(db, "bundle-test-worker")


@pytest.fixture
def bundle_source(monkeypatch):
    payloads = {
        "encoder.pt": b"verified encoder",
        "weights.safetensors": b"z" * (2 * files.CHUNK + 8),
        "tokens.json": b'{"token":1}',
    }
    entry = BUNDLES[0].model_copy(
        update={
            "files": tuple(
                BundleFile(
                    filename=name,
                    file=files.FileSpec(
                        sha256=hashlib.sha256(value).hexdigest(),
                        size_bytes=len(value),
                        urls=("https://models.example.com/pinned/" + name,),
                    ),
                )
                for name, value in payloads.items()
            )
        }
    )
    monkeypatch.setattr(bundle_setup, "BUNDLES", (entry,))
    monkeypatch.setattr(bundle_setup, "bundle", lambda identity: entry if identity == entry.id else None)
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"memory": {"available_mib": 16384}})
    state = {
        "entry": entry,
        "payloads": payloads,
        "calls": [],
        "stop": False,
        "api": None,
        "task": None,
        "corrupt": False,
        "hook": None,
    }

    class Stream(httpx.AsyncByteStream):
        def __init__(self, name, content):
            self.name, self.content = name, content

        async def __aiter__(self):
            yield self.content[: files.CHUNK]
            if state["stop"] and self.name == "weights.safetensors":
                state["stop"] = False
                response = state["api"].post("/api/setup/bundles/downloads/" + state["task"] + "/cancel")
                assert response.status_code == 200
            if self.content[files.CHUNK :]:
                yield self.content[files.CHUNK :]

    @asynccontextmanager
    async def response(url, offset, check):
        name = url.rsplit("/", 1)[1]
        state["calls"].append((name, offset))
        if state["hook"]:
            state["hook"](name)
        full = payloads[name]
        content = (b"x" * len(full) if state["corrupt"] and name == "tokens.json" else full)[offset:]
        headers = {"Content-Length": str(len(content))}
        if offset:
            headers["Content-Range"] = f"bytes {offset}-{len(full) - 1}/{len(full)}"
        result = httpx.Response(
            206 if offset else 200,
            headers=headers,
            stream=Stream(name, content),
            request=httpx.Request("GET", url),
        )
        try:
            yield result
        finally:
            await result.aclose()

    monkeypatch.setattr(files, "response", response)
    return state


def test_windows_unknown_capacity_preserves_bundle_partial_without_network(bundle_source, monkeypatch):
    entry = bundle_source["entry"]
    partial = files.directory(get_settings().data_dir) / (entry.files[0].file.sha256 + ".part")
    partial.write_bytes(b"ver")
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "memory": {"available_mib": 16384},
            "disk": {"physical_storage": {"status": "unavailable", "source": "windows_volume"}},
        },
    )
    with TestClient(app) as api:
        assert api.get("/api/setup/bundles/catalog").json()["storage"] is None
        created = api.post("/api/setup/bundles/downloads", json=body(entry))
        assert created.status_code == 202
        work()
        result = api.get("/api/setup/bundles/downloads/" + created.json()["id"]).json()
        assert result["run"]["status"] == "failed"
        assert "Windows controls" in result["run"]["error_message"]
        assert not bundle_source["calls"]
        assert partial.read_bytes() == b"ver"


def test_bundle_source_recovery_uses_verified_bytes_and_audits_the_original_snapshot(
    bundle_source, monkeypatch
):
    entry = bundle_source["entry"]
    first = entry.files[0]
    repository, old, new = "publisher/model-bundle", "1" * 40, "2" * 40
    missing = f"https://huggingface.co/{repository}/resolve/{old}/{first.filename}"
    recovered = f"https://huggingface.co/{repository}/resolve/{new}/{first.filename}"
    metadata_url = f"https://huggingface.co/api/models/{repository}/revision/main?blobs=true"
    changed = first.model_copy(update={"file": first.file.model_copy(update={"urls": (missing,)})})
    entry = entry.model_copy(update={"files": (changed, *entry.files[1:])})
    monkeypatch.setattr(bundle_setup, "BUNDLES", (entry,))
    monkeypatch.setattr(bundle_setup, "bundle", lambda identity: entry if identity == entry.id else None)
    original = files.response

    @asynccontextmanager
    async def source(url, offset, check):
        if url in {missing, metadata_url}:
            data = {
                "sha": new,
                "siblings": [
                    {
                        "rfilename": first.filename,
                        "lfs": {"sha256": first.file.sha256, "size": first.file.size_bytes},
                    }
                ],
            }
            result = httpx.Response(
                404 if url == missing else 200,
                stream=httpx.ByteStream(json.dumps(data).encode()),
                request=httpx.Request("GET", url),
            )
            try:
                yield result
            finally:
                await result.aclose()
        else:
            async with original(url, offset, check) as result:
                yield result

    monkeypatch.setattr(files, "response", source)
    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(entry)).json()
        work()
        result = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert result["run"]["status"] == "succeeded", result
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            assert run.parameters["entry"] == entry.model_dump(mode="json")
            assert run.parameters["manifest_sha256"] == bundle_setup.fingerprint(run.parameters["entry"])
            event = db.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == run.id, RunEvent.event_type == "model.download.source_refreshed"
                )
            )
            assert event.payload == {
                "sha256": first.file.sha256,
                "filename": first.filename,
                "source_url": recovered,
            }


def test_complete_bundle_is_durable_idempotent_shared_files_with_private_receipt(bundle_source):
    with TestClient(app) as api:
        entry = bundle_source["entry"]
        catalog = api.get("/api/setup/bundles/catalog").json()
        assert catalog["can_prepare"] and catalog["bundles"][0]["size_bytes"] == entry.size_bytes
        request = body(entry)
        result = api.post("/api/setup/bundles/downloads", json=request)
        assert result.status_code == 202, result.text
        identity = result.json()["id"]
        assert not bundle_source["calls"]
        assert api.post("/api/setup/bundles/downloads", json=request).json()["id"] == identity
        assert work() == result.json()["run"]["id"]
        value = api.get("/api/setup/bundles/downloads/" + identity).json()
        assert value["run"]["status"] == "succeeded", value["run"]["error_message"]
        assert (
            value["progress"]["completed_files"] == 3
            and value["progress"]["verified_bytes"] == entry.size_bytes
        )
        assert not value["runtime_prepared"] and not value["ready_to_try"]
        with control_session_factory()() as db:
            records = list(db.scalars(select(ModelFile)))
            assert len(records) == 3 and all(v.host_path is None and v.category == "audio" for v in records)
            assert set(value["model_file_ids"]) == {v.id for v in records}
            assert not list(db.scalars(select(ModelDefinition)))
            output = db.scalar(select(Artifact).where(Artifact.run_id == value["run"]["id"]))
            report = json.loads((get_settings().data_dir / output.relative_path).read_text())
            assert len(report["files"]) == 3 and not report["runtime_prepared"]
            assert all(v["relative_path"] == "models/store/" + v["sha256"] for v in report["files"])
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        assert "model.bundle.verified" in api.get("/api/runs/" + value["run"]["id"] + "/stream").text
        assert len(api.get("/api/setup/bundles/downloads").json()) == 1
        api.post("/api/setup/bundles/downloads", json=body(entry)).raise_for_status()
        work()
        assert bundle_source["calls"] == [(v.filename, 0) for v in entry.files]
        with control_session_factory()() as db:
            assert len(list(db.scalars(select(ModelFile)))) == 3


def test_stop_retains_objects_and_partial_then_resume_keeps_original_manifest(bundle_source, monkeypatch):
    with TestClient(app) as api:
        entry = bundle_source["entry"]
        created = api.post("/api/setup/bundles/downloads", json=body(entry)).json()
        bundle_source.update(api=api, task=created["id"], stop=True)
        work()
        current = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert current["run"]["status"] == "canceled"
        folder = files.directory(get_settings().data_dir)
        partial = folder / (entry.files[1].file.sha256 + ".part")
        assert partial.stat().st_size == files.CHUNK and (folder / entry.files[0].file.sha256).is_file()
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
        monkeypatch.setattr(bundle_setup, "BUNDLES", ())
        monkeypatch.setattr(bundle_setup, "bundle", lambda _: None)
        request = {"client_request_id": str(uuid4()), "expected_run_id": current["run"]["id"]}
        endpoint = "/api/setup/bundles/downloads/" + created["id"] + "/resume"
        resumed = api.post(endpoint, json=request)
        assert resumed.status_code == 202, resumed.text
        assert api.post(endpoint, json=request).json()["run"]["id"] == resumed.json()["run"]["id"]
        work()
        current = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert current["run"]["status"] == "succeeded", current["run"]["error_message"]
        assert current["entry"] == entry.model_dump(mode="json") and current["attempt"] == 2
        assert bundle_source["calls"] == [
            (entry.files[0].filename, 0),
            (entry.files[1].filename, 0),
            (entry.files[1].filename, files.CHUNK),
            (entry.files[2].filename, 0),
        ]
        assert current["run"]["parent_run_id"] == created["run"]["id"] and not partial.exists()


def test_bad_last_object_cannot_publish_a_partial_bundle(bundle_source):
    with TestClient(app) as api:
        bundle_source["corrupt"] = True
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        work()
        value = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert value["run"]["status"] == "failed"
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(Artifact)))
        assert len(list(files.directory(get_settings().data_dir).glob("*.part"))) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"license_accepted": False},
        {"license_accepted": "true"},
        {"url": "https://example.com"},
        {"manifest_sha256": "0" * 64},
        {"catalog_id": "unknown"},
    ],
)
def test_api_rejects_unreviewed_sources_or_missing_consent(bundle_source, change):
    with TestClient(app) as api:
        assert api.post(
            "/api/setup/bundles/downloads", json={**body(bundle_source["entry"]), **change}
        ).status_code in {409, 422}
        assert not api.get("/api/setup/bundles/downloads").json() and not bundle_source["calls"]


def test_ram_pressure_defers_without_starting_a_transfer(bundle_source, monkeypatch):
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"memory": {"available_mib": 100}})
    with TestClient(app) as api:
        value = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        work()
        run = api.get("/api/runs/" + value["run"]["id"]).json()
        assert run["status"] == "queued" and run["worker_id"] is None
        assert run["metadata"]["resource_wait"]["reason"] == "memory" and not bundle_source["calls"]


def test_stale_worker_requires_explicit_inspection_then_resume(bundle_source):
    from app.recovery import recover_stale
    from app.runner_client import RunnerUnavailable

    class Offline:
        def inspect_process(self, *args):
            raise RunnerUnavailable("Synthetic runner outage")

    with TestClient(app) as api:
        created = api.post("/api/setup/bundles/downloads", json=body(bundle_source["entry"])).json()
        with control_session_factory()() as db:
            run = db.get(Run, created["run"]["id"])
            run.status, run.worker_id = "running", "lost-worker"
            run.claimed_at, run.lease_expires_at = (
                utcnow() - timedelta(minutes=10),
                utcnow() - timedelta(minutes=1),
            )
            db.commit()
            recover_stale(db, Offline())
            db.commit()
        current = api.get("/api/setup/bundles/downloads/" + created["id"]).json()
        assert (
            current["run"]["status"] == "interrupted"
            and current["resume_allowed"]
            and not bundle_source["calls"]
        )


def test_publisher_bundle_is_complete_immutable_and_named_safely():
    entry = BUNDLES[0]
    assert entry.size_bytes == 3208951924 and len(entry.files) == 6
    assert all(entry.revision in item.file.urls[0] for item in entry.files)
    for name in ("../escape", "/absolute", "sub/path", "a\\b", ".."):
        with pytest.raises(ValidationError):
            BundleFile(filename=name, file=entry.files[0].file)
    with pytest.raises(ValidationError):
        Bundle.model_validate({**entry.model_dump(), "files": (entry.files[0], entry.files[0])})
