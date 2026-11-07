"""New-protocol qualification with raw framework messages and durable real children."""

import json

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import implemented_media as implemented_media
from test_assistant_controller import drain, root_state, submit
from test_images import bridge as bridge
from test_images import upload


def action(name, **arguments):
    return f"Thought: Execute the requested step.\nAction: {name}\nAction Input: {json.dumps(arguments)}"


@pytest.fixture
def react_model(monkeypatch):
    state = {"calls": [], "actions": [], "immediate": [], "automations": []}
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def stream(self, **params):
        state["calls"].append(params)
        first = params["messages"][0]["content"]
        if first.startswith("Infer the user's requested outcomes"):
            schema = json.loads(params["messages"][1]["content"])["outcome_schema"]
            assert "automations" in schema["properties"]
            yield json.dumps(
                {
                    "reason": "Fulfil the request",
                    "immediate": state["immediate"],
                    "automations": state["automations"],
                }
            )
        elif "Action Input" in first:
            assert not params.get("json_output"), "ReAct is a text tool protocol, not a JSON completion"
            assert state["actions"], "Unexpected extra framework round"
            yield state["actions"].pop(0)
        elif "proposal_schema" in json.dumps(params["messages"]) and state.get("proposal"):
            yield json.dumps(state["proposal"])
        else:
            yield "The cabinet has four shelves."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return state


@pytest.mark.parametrize("wrong_reference_first", [False, True])
def test_transform_then_recurring_agent_uses_actual_result_and_exact_cadence(
    react_model, bridge, implemented_media, wrong_reference_first
):
    react_model["immediate"] = [
        {
            "kind": "image",
            "description": "A blue cabinet in a garden",
            "reference_mode": "provided",
            "source_inputs": ["input:image:1"],
        }
    ]
    react_model["automations"] = [
        {
            "goal": "Show this cabinet in a different setting each time",
            "media_kind": "image",
            "image_source": "latest_result",
            "schedule": {"trigger": "interval", "interval_seconds": 900},
            "vary_results": True,
        }
    ]
    react_model["actions"] = [
        action(
            "image_recompose",
            instruction="A blue cabinet in a garden",
            images=["input:image:1"],
            image_model="qwen",
        )
    ]
    if wrong_reference_first:
        react_model["actions"].append(
            action(
                "agent_create",
                instruction="New cabinet views",
                images=["input:image:1"],
                interval_seconds=900,
            )
        )
    react_model["actions"] += [
        action(
            "agent_create", instruction="New cabinet views", images=["step:1:image:1"], interval_seconds=900
        ),
        "Thought: Summarize the observed results.\nAnswer: The image and disabled recurring agent are ready for review.",
    ]
    with TestClient(app) as api:
        original = upload(api)["id"]
        result = submit(
            api,
            "Change this cabinet, then create an agent that varies the changed result every 15 minutes",
            image_artifact_ids=[original],
        )
        drain()
        state = root_state(result)
        assert state["controller_outcome"] == "finish", state
        assert [row["tool"] for row in state["controller_steps"]] == ["image.recompose", "agent.create"]
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            assert root.parameters["controller_protocol"] == "llamaindex-react-v1"
            photos = list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))
            assert len(photos) == 1 and photos[0].status == "succeeded"
            assert photos[0].parameters["backend"] == "qwen"
            assert photos[0].parameters["steps"] == 30 and photos[0].parameters["cfg"] == 6
            output = db.scalar(
                select(Artifact).where(Artifact.run_id == photos[0].id, Artifact.artifact_type == "image")
            )
            agent = db.scalar(select(Agent))
            assert agent is not None and not agent.enabled and agent.next_run_at is None
            assert agent.trigger == "interval" and agent.interval_seconds == 900
            assert agent.media["request"]["input_artifact_ids"] == [output.id]
            assert output.id != original
            assert agent.media["request"]["backend"] == "qwen"
            assert agent.media["request"]["steps"] == 30 and agent.media["request"]["cfg"] == 6
            assert agent.media["vary_scenes"] is True
            draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
            assert draft.parameters["media_agent_scope"]["images"][0]["snapshot"]["id"] == output.id
        assert not react_model["actions"]
        # A fresh session and worker for each tick reconstructed real observations.
        transcripts = "\n".join(
            message["content"] for call in react_model["calls"] for message in call["messages"]
        )
        assert '"status": "succeeded"' in transcripts and "step:1:image:1" in transcripts


def test_agent_only_creates_no_unsolicited_preview(react_model, implemented_media):
    react_model["automations"] = [
        {
            "goal": "A watercolor landscape",
            "media_kind": "image",
            "schedule": {"trigger": "interval", "interval_seconds": 1800},
        }
    ]
    react_model["actions"] = [
        action("agent_create", instruction="A watercolor landscape every 30 minutes", interval_seconds=1800),
        "Thought: Done.\nAnswer: Your disabled agent is ready for review.",
    ]
    with TestClient(app) as api:
        result = submit(api, "Create an agent that makes a watercolor landscape every 30 minutes")
        drain()
        assert root_state(result)["controller_outcome"] == "finish"
        with session_factory()() as db:
            assert not list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))
            agent = db.scalar(select(Agent))
            assert agent and not agent.enabled and agent.interval_seconds == 1800


def test_ordinary_answer_still_streams_through_chat(react_model):
    react_model["immediate"] = [{"kind": "text", "description": "Explain cabinet construction"}]
    react_model["actions"] = [action("chat_reply", instruction="Explain cabinet construction")]
    with TestClient(app) as api:
        result = submit(api, "Explain cabinet construction")
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        messages = api.get("/api/chat/conversations/" + result["conversation_id"]).json()["messages"]
        assert any(row["content"] == "The cabinet has four shelves." for row in messages)


def test_clarification_keeps_the_attachment_on_the_new_protocol(react_model, bridge):
    react_model["immediate"] = [
        {
            "kind": "image",
            "description": "A changed cabinet",
            "reference_mode": "provided",
            "source_inputs": ["input:image:1"],
        }
    ]
    react_model["actions"] = [action("ask_user", question="Would you prefer a garden or a studio?")]
    with TestClient(app) as api:
        original = upload(api)["id"]
        first = submit(
            api, "Change this cabinet's scene; ask which scene first", image_artifact_ids=[original]
        )
        drain()
        assert root_state(first)["controller_outcome"] == "clarify"
        react_model["immediate"] = [
            {
                "kind": "image",
                "description": "The same cabinet in a garden",
                "reference_mode": "provided",
                "source_inputs": ["previous:image:1"],
            }
        ]
        react_model["actions"] = [
            action(
                "image_recompose",
                instruction="The same cabinet in a sunny garden",
                images=["previous:image:1"],
            ),
            "Thought: Done.\nAnswer: The changed image is ready.",
        ]
        response = api.post(
            "/api/chat/conversations/" + first["conversation_id"] + "/messages",
            json={
                "content": "The garden, please. Edit it now.",
                "execution_mode": "assistant",
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        drain()
        with session_factory()() as db:
            root = db.get(Run, run_id)
            assert root.status == "succeeded" and root.metadata_json["controller_outcome"] == "finish"
            assert root.parameters["controller_inputs"][0]["snapshot"]["id"] == original
            assert any(
                row["content"] == "Would you prefer a garden or a studio?"
                for row in root.parameters["planner_context"]
            )
            photo = db.scalar(select(Run).where(Run.executor_type == "photo_pipe"))
            assert photo.parameters["parent_artifact_ids"] == [original]


def test_stop_during_framework_inference_cannot_publish_an_image(react_model, monkeypatch):
    from app.task_control import cancel_task

    react_model["immediate"] = [
        {"kind": "image", "description": "A cabinet", "reference_mode": "independent"}
    ]
    original = LocalChatProvider.stream

    async def stop(self, **params):
        if "Action Input" in params["messages"][0]["content"]:
            with session_factory()() as db:
                root = db.scalar(select(Run).where(Run.executor_type == "assistant_controller"))
                cancel_task(db, root.task)
                db.commit()
            yield action("image_generate", instruction="A blue cabinet")
        else:
            async for token in original(self, **params):
                yield token

    monkeypatch.setattr(LocalChatProvider, "stream", stop)
    with TestClient(app) as api:
        result = submit(api, "Create a cabinet image")
        drain()
        with session_factory()() as db:
            assert db.get(Run, result["run"]["id"]).status == "canceled"
            assert not list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))


@pytest.mark.parametrize("tamper", ["trash", "hash", "draft_scope"])
def test_future_agent_cannot_publish_from_changed_or_tampered_sources(react_model, implemented_media, tamper):
    from app.db import utcnow
    from app.engine import tick

    react_model["automations"] = [
        {
            "goal": "A new view of the cabinet",
            "media_kind": "image",
            "image_source": "supplied",
            "source_images": ["input:image:1"],
            "schedule": {"trigger": "interval", "interval_seconds": 900},
        }
    ]
    react_model["actions"] = [
        action("agent_create", instruction="Cabinet views", images=["input:image:1"], interval_seconds=900),
        action("ask_user", question="The source changed. Please choose an available reference."),
    ]
    with TestClient(app) as api:
        image = upload(api)["id"]
        submit(api, "Create an agent using this reference every 15 minutes", image_artifact_ids=[image])
        for index in range(20):
            with session_factory()() as db:
                tick(db, "prepare-draft-" + str(index))
                draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
                if draft is None:
                    continue
                assert draft.status == "queued"
                if tamper == "draft_scope":
                    scope = {
                        **draft.parameters["media_agent_scope"],
                        "plan": {
                            **draft.parameters["media_agent_scope"]["plan"],
                            "goal": "A substituted goal",
                        },
                    }
                    draft.parameters = {**draft.parameters, "media_agent_scope": scope}
                else:
                    source = db.get(Artifact, image)
                    if tamper == "trash":
                        source.trashed_at = utcnow()
                    else:
                        source.sha256 = "b" * 64
                db.commit()
                break
        else:
            raise AssertionError("No queued source-bound draft")
        drain()
        with session_factory()() as db:
            assert not list(db.scalars(select(Agent)))
            draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
            assert draft.status == "failed", draft.error_message


def test_raw_react_can_chain_web_two_images_and_a_different_future_media_agent(
    react_model, bridge, implemented_media, monkeypatch
):
    from app import web_search
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9")
    clear_settings_cache()

    async def search(query):
        return {
            "query": query,
            "provider": "fake",
            "sources": [
                {
                    "title": "Cabinet design",
                    "url": "https://example.com/design",
                    "snippet": "Oak finish and brass hardware",
                }
            ],
            "partial": False,
        }

    monkeypatch.setattr(web_search, "search", search)
    react_model["immediate"] = [
        {
            "kind": "image",
            "count": 2,
            "description": "Two related cabinet images",
            "reference_mode": "sequential",
        }
    ]
    react_model["automations"] = [
        {
            "goal": "Create an avatar with the latest world news",
            "media_kind": "avatar",
            "public_query": "latest world news",
            "schedule": {"trigger": "interval", "interval_seconds": 86400},
        }
    ]
    react_model["proposal"] = {
        "name": "Daily world news avatar",
        "goal": "Create an avatar with the latest world news",
        "tools": ["web_search", "create_media"],
        "search_query": "latest world news",
        "trigger": "interval",
        "interval_seconds": 86400,
        "media": {
            "kind": "avatar",
            "description_source": "goal",
            "request": {"speech_text": "Summarize today's verified world news"},
        },
    }
    react_model["actions"] = [
        action("web_search", query="Oak cabinet design"),
        action(
            "image_generate",
            instruction="A neutral oak cabinet with brass hardware based on the researched design",
        ),
        action(
            "image_recompose",
            instruction="Place the same oak cabinet in a blue studio",
            images=["step:2:image:1"],
        ),
        action(
            "agent_create",
            instruction="Prepare an agent that creates an avatar with the latest world news every 24 hours",
            interval_seconds=86400,
        ),
        "Thought: Summarize actual work.\nAnswer: Both images and the disabled daily avatar agent are ready for review.",
    ]
    with TestClient(app) as api:
        result = submit(
            api,
            "Research cabinet design online, create an image from it, create another image using that result, then create an agent that makes a world news avatar every 24 hours",
            web_search={"enabled": True},
        )
        drain()
        state = root_state(result)
        assert state["controller_outcome"] == "finish", state
        assert [step["tool"] for step in state["controller_steps"]] == [
            "web.search",
            "image.generate",
            "image.recompose",
            "agent.create",
        ]
        with session_factory()() as db:
            photos = list(
                db.scalars(select(Run).where(Run.executor_type == "photo_pipe").order_by(Run.created_at))
            )
            assert len(photos) == 2 and all(row.status == "succeeded" for row in photos)
            first = db.scalar(
                select(Artifact.id).where(Artifact.run_id == photos[0].id, Artifact.artifact_type == "image")
            )
            assert photos[1].parameters["parent_artifact_ids"] == [first]
            agent = db.scalar(select(Agent))
            assert agent and not agent.enabled and agent.interval_seconds == 86400
            assert agent.media["kind"] == "avatar" and "web_search" in agent.tools


def test_failed_reply_is_observed_without_masking_its_error(react_model, monkeypatch):
    from app.providers import ProviderError

    react_model["immediate"] = [{"kind": "text", "description": "Explain the requested subject"}]
    react_model["actions"] = [
        action("chat_reply", instruction="Explain the requested subject"),
        action("ask_user", question="The response was interrupted. Would you like to continue?"),
    ]
    original = LocalChatProvider.stream

    async def failing_reply(self, **params):
        first = params["messages"][0]["content"]
        if first.startswith("Infer the user's requested outcomes") or "Action Input" in first:
            async for token in original(self, **params):
                yield token
        else:
            yield "An actual partial explanation."
            raise ProviderError("Synthetic provider disconnect")

    monkeypatch.setattr(LocalChatProvider, "stream", failing_reply)
    with TestClient(app) as api:
        result = submit(api, "Explain the requested subject")
        drain()
        state = root_state(result)
        assert state["controller_outcome"] == "clarify"
        observation = state["controller_steps"][0]["observation"]
        assert observation["status"] == "failed"
        assert observation["errors"][0]["error"] == "Synthetic provider disconnect"
        messages = api.get("/api/chat/conversations/" + result["conversation_id"]).json()["messages"]
        partial = next(row for row in messages if row["content"] == "An actual partial explanation.")
        assert partial["run_status"] == "failed" and partial["metadata"]["partial"] is True
        assert not react_model["actions"]
