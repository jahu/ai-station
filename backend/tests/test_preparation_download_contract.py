"""All shared media setup inputs honor download storage and audit contracts."""

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from app import download_storage, runtime_setup_api, speech_setup_job
from app import model_download_files as files
from app.api import app
from app.config import get_settings
from app.db import control_session_factory
from app.engine import tick
from app.models import RunEvent
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_avatar_setup_job import avatar_source as avatar_source
from test_effects_setup_job import effects_source as effects_source
from test_fish_setup_job import fish_source as fish_source
from test_image_setup_job import image_source as image_source
from test_model_bundles import bundle_source as bundle_source
from test_music_setup_job import music_source as music_source
from test_speech_setup_job import speech_source as speech_source
from test_video_setup_job import video_source as video_source

FAMILIES = [
    "speech_source",
    "image_source",
    "video_source",
    "music_source",
    "avatar_source",
    "effects_source",
    "fish_source",
]
GIB = 1024**3


def enqueue(api, source):
    recipe = source["recipe"]
    response = api.post(
        "/api/setup/runtimes",
        json={
            "client_request_id": str(uuid4()),
            "profile": recipe["profile"],
            "manifest_sha256": runtime_setup_api.fingerprint(recipe),
            "license_accepted": True,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def work():
    with control_session_factory()() as db:
        tick(db, "shared-preparation-download-contract")


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "physical", [{"status": "unknown"}, {"status": "ready", "free_bytes": GIB, "total_bytes": 100 * GIB}]
)
def test_every_media_setup_refuses_unknown_or_insufficient_physical_space_before_network(
    request, monkeypatch, family, physical
):
    source = request.getfixturevalue(family)
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {"memory": {"available_mib": 131072}, "disk": {"physical_storage": physical}},
    )
    monkeypatch.setattr(
        download_storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=500 * GIB, total=500 * GIB)
    )
    with TestClient(app) as api:
        created = enqueue(api, source)
        work()
        value = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert value["run"]["status"] == "failed", value
        assert not source["source"]["calls"] and not source["starts"]


@pytest.mark.parametrize("family", FAMILIES)
def test_every_media_setup_records_recovered_source_without_changing_its_frozen_recipe(
    request, monkeypatch, family
):
    source = request.getfixturevalue(family)
    original = speech_setup_job.obtain
    recovered = "https://huggingface.co/publisher/model/resolve/" + "a" * 40 + "/weights.gguf"

    async def obtain(root, spec, *, check, progress, source_recovered=lambda url: None):
        source_recovered(recovered)
        return await original(root, spec, check=check, progress=progress)

    monkeypatch.setattr(speech_setup_job, "obtain", obtain)
    with TestClient(app) as api:
        created = enqueue(api, source)
        work()
        value = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert value["run"]["status"] == "succeeded", value
        assert value["recipe"] == source["recipe"]
        with control_session_factory()() as db:
            events = list(
                db.scalars(
                    select(RunEvent).where(
                        RunEvent.run_id == created["run"]["id"],
                        RunEvent.event_type == "model.download.source_refreshed",
                    )
                )
            )
            assert len(events) == len(source["recipe"]["inputs"])
            assert all(event.payload["source_url"] == recovered for event in events)


def test_runtime_setup_credits_a_retained_partial_and_preserves_assembly_headroom(speech_source, monkeypatch):
    source = speech_source
    first = source["recipe"]["inputs"][0]
    content = source["source"]["payloads"][first["filename"]]
    folder = files.directory(get_settings().data_dir)
    partial = folder / (first["sha256"] + ".part")
    fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content[:4])
    needed = sum(v["size_bytes"] for v in source["recipe"]["inputs"]) - 4
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "memory": {"available_mib": 131072},
            "disk": {
                "physical_storage": {
                    "status": "ready",
                    "free_bytes": 8 * GIB + needed,
                    "total_bytes": 200 * GIB,
                }
            },
        },
    )
    monkeypatch.setattr(
        download_storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=500 * GIB, total=500 * GIB)
    )
    with TestClient(app) as api:
        created = enqueue(api, source)
        work()
        value = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert value["run"]["status"] == "succeeded", value
        assert source["source"]["calls"][0] == (first["filename"], 4)
        assert not partial.exists() and len(source["starts"]) == 1


def test_runtime_setup_losing_physical_observation_mid_transfer_keeps_its_partial(speech_source, monkeypatch):
    source = speech_source
    first = source["recipe"]["inputs"][0]
    content = source["source"]["payloads"][first["filename"]]
    clock = [0]
    report = {"status": "ready", "free_bytes": 100 * GIB, "total_bytes": 200 * GIB}
    monkeypatch.setattr(download_storage, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {"memory": {"available_mib": 131072}, "disk": {"physical_storage": dict(report)}},
    )
    monkeypatch.setattr(
        download_storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=500 * GIB, total=500 * GIB)
    )

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield content[:4]
            clock[0] = 10
            report.clear()
            report["status"] = "unknown"
            yield content[4:]

    @asynccontextmanager
    async def response(url, offset, check):
        assert url == first["url"] and offset == 0
        result = httpx.Response(200, stream=Stream(), request=httpx.Request("GET", url))
        try:
            yield result
        finally:
            await result.aclose()

    monkeypatch.setattr(files, "response", response)
    # Small chunks expose the actual first write before the next quota refresh.
    monkeypatch.setattr(files, "CHUNK", 4)
    with TestClient(app) as api:
        created = enqueue(api, source)
        work()
        value = api.get("/api/setup/runtimes/preparations/" + created["id"]).json()
        assert value["run"]["status"] == "failed" and "Windows" in value["run"]["error_message"]
        partial = files.directory(get_settings().data_dir) / (first["sha256"] + ".part")
        assert partial.read_bytes() == content[:4]
        assert not source["starts"]
