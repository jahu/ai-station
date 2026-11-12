"""Ordinary durable controller + real owned files; fake HTTP/model/photo executor."""

import asyncio

from app.api import app
from app.assistant_controller import controller_results, missing_outcomes
from app.config import clear_settings_cache
from app.db import session_factory
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import bridge as bridge
from test_assistant_controller import drain, finish, root_state, submit, tool
from test_assistant_controller import model as model
from test_assistant_react_workflow import action
from test_assistant_react_workflow import react_model as react_model
from test_web_images import pixels


def setup(monkeypatch, model):
    from app import web_images

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9999")
    clear_settings_cache()

    async def search(query):
        return {
            "sources": [
                {
                    "title": "Neutral blue object",
                    "url": "https://photos.example.com/one.png",
                    "page_url": "https://example.com/photo",
                    "kind": "image",
                }
            ]
        }

    async def download(url):
        assert url == "https://photos.example.com/one.png"
        return pixels(), url

    monkeypatch.setattr(web_images, "search_images", search)
    monkeypatch.setattr(web_images, "download_image", download)
    model["outcomes"] = [
        {
            "kind": "image",
            "count": 1,
            "description": "An edited photograph found online",
            "reference_mode": "web",
        }
    ]
    model["decisions"] = [
        tool("web.image_search", query="neutral blue object"),
        tool("web.image_import", sources=["step:1:source:1"]),
        tool(
            "image.recompose", instruction="Place the original object in a garden", images=["step:2:image:1"]
        ),
        finish(3),
    ]


def test_search_import_edit_retains_visible_source_and_requires_actual_transformation(
    model, bridge, monkeypatch
):
    setup(monkeypatch, model)
    with TestClient(app) as api:
        submitted = submit(
            api,
            "Find a public object photograph and then put that object in a garden",
            web_search={"enabled": True},
        )
        drain()
        state = root_state(submitted)
        steps = state["controller_steps"]
        assert [s["tool"] for s in steps] == ["web.image_search", "web.image_import", "image.recompose"]
        assert missing_outcomes([steps[1]["observation"]], state["controller_outcomes"])
        with session_factory()() as db:
            root = db.get(Run, submitted["run"]["id"])
            original_id = steps[1]["artifacts"][0]["snapshot"]["id"]
            original = db.get(Artifact, original_id)
            assert original.metadata_json["reference_only"] is True
            assert original.metadata_json["source_url"] == "https://photos.example.com/one.png"
            result = controller_results(db, root)
            assert result["controller_steps"][1]["result"]["artifacts"][0]["id"] == original_id
            edited = steps[2]["artifacts"][0]["snapshot"]["id"]
            assert edited != original_id and db.get(Artifact, edited).run_id != original.run_id
            assert not db.scalar(
                select(Run.id).where(
                    Run.executor_type == "photo_pipe",
                    Run.parameters["request"]["operation"].as_string() == "t2i",
                )
            )


def test_stop_cancels_inflight_download_without_import_or_edit(model, bridge, monkeypatch):
    from app import web_images
    from app.task_control import cancel_task

    setup(monkeypatch, model)
    canceled = []

    async def download(url):
        with session_factory()() as db:
            run = db.scalar(
                select(Run).where(
                    Run.executor_type == "assistant_web",
                    Run.status == "running",
                    Run.parameters["tool"].as_string() == "web.image_import",
                )
            )
            assert run
            cancel_task(db, run.task)
            db.commit()
        try:
            await asyncio.sleep(30)
        finally:
            canceled.append(True)

    monkeypatch.setattr(web_images, "download_image", download)
    with TestClient(app) as api:
        submitted = submit(api, "Find and edit an image", web_search={"enabled": True})
        drain()
        with session_factory()() as db:
            root = db.get(Run, submitted["run"]["id"])
            assert root.status == "canceled"
            assert not list(db.scalars(select(Artifact).where(Artifact.artifact_type == "image")))
            assert not db.scalar(select(Run.id).where(Run.executor_type == "photo_pipe"))
        assert canceled == [True]


def test_current_react_protocol_searches_imports_then_edits(react_model, bridge, monkeypatch):
    from app import web_images
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9999")
    clear_settings_cache()

    async def search(query):
        return {"sources": [{"url": "https://photos.example.com/one.png", "kind": "image"}]}

    async def download(url):
        return pixels(), url

    monkeypatch.setattr(web_images, "search_images", search)
    monkeypatch.setattr(web_images, "download_image", download)
    react_model["immediate"] = [
        {"kind": "image", "description": "Edit an image found online", "reference_mode": "web"}
    ]
    react_model["actions"] = [
        action("web_image_search", query="blue object"),
        action("web_image_import", sources=["step:1:source:1"]),
        action("image_recompose", instruction="Place this object in a garden", images=["step:2:image:1"]),
        "Thought: Finished.\nAnswer: The source and edited image are ready.",
    ]
    with TestClient(app) as api:
        submitted = submit(
            api,
            "Find a blue object image online and put that object in a garden",
            web_search={"enabled": True},
        )
        drain()
        state = root_state(submitted)
        assert state["controller_outcome"] == "finish"
        assert [s["tool"] for s in state["controller_steps"]] == [
            "web.image_search",
            "web.image_import",
            "image.recompose",
        ]
        assert not react_model["actions"]


def test_cancellation_at_download_completion_fences_publication(model, bridge, monkeypatch):
    from app import web_images
    from app.task_control import cancel_task

    setup(monkeypatch, model)

    async def download(url):
        with session_factory()() as db:
            run = db.scalar(
                select(Run).where(
                    Run.executor_type == "assistant_web",
                    Run.status == "running",
                    Run.parameters["tool"].as_string() == "web.image_import",
                )
            )
            cancel_task(db, run.task)
            db.commit()
        return pixels(), url

    monkeypatch.setattr(web_images, "download_image", download)
    with TestClient(app) as api:
        submitted = submit(api, "Find and edit an image", web_search={"enabled": True})
        drain()
        with session_factory()() as db:
            assert db.get(Run, submitted["run"]["id"]).status == "canceled"
            assert not db.scalar(select(Artifact.id).where(Artifact.artifact_type == "image"))


def test_multiple_imported_candidates_do_not_force_every_candidate_into_single_image_edit(
    model, bridge, monkeypatch
):
    from app import web_images

    setup(monkeypatch, model)

    async def search(query):
        return {
            "sources": [
                {"url": "https://photos.example.com/one.png"},
                {"url": "https://photos.example.com/two.png"},
            ]
        }

    async def download(url):
        return pixels(), url

    monkeypatch.setattr(web_images, "search_images", search)
    monkeypatch.setattr(web_images, "download_image", download)
    model["decisions"] = [
        tool("web.image_search", query="blue object"),
        tool("web.image_import", sources=["step:1:source:1", "step:1:source:2"]),
        tool("image.edit", instruction="Change the color of the selected object", images=["step:2:image:1"]),
        finish(3),
    ]
    with TestClient(app) as api:
        submitted = submit(
            api, "Find a photograph online and edit the chosen image", web_search={"enabled": True}
        )
        drain()
        state = root_state(submitted)
        assert state["controller_outcome"] == "finish"
        assert len(state["controller_steps"][1]["artifacts"]) == 2
        assert state["controller_steps"][2]["tool"] == "image.edit"
