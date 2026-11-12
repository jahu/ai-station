import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import implemented_media as implemented_media
from test_chat_pages import page_tools as page_tools
from test_images import bridge as bridge
from test_images import upload
from test_vision import vision_runtime as vision_runtime


def tool(name, **arguments):
    return {"kind": "tool", "reason": "Perform the requested step", "tool": name, "arguments": arguments}


def finish(*evidence):
    return {
        "kind": "finish",
        "reason": "Requested work completed",
        "response": "The requested results are ready.",
        "evidence": list(evidence),
    }


@pytest.fixture
def model(monkeypatch, legacy_controller_protocol):
    state = {
        "decisions": [],
        "intent_calls": [],
        "calls": [],
        "reply": "A streaming answer",
        "outcomes": [{"kind": "image", "count": 1, "description": "A transformed reference image"}],
        "proposal": {
            "name": "Daily observer",
            "goal": "Report actual workstation state",
            "tools": ["system_snapshot"],
            "trigger": "interval",
            "interval_seconds": 86400,
        },
    }
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def stream(self, **params):
        first = params["messages"][0]["content"]
        if isinstance(first, str) and first.startswith("Infer the user's requested outcomes"):
            state["intent_calls"].append(params)
            yield json.dumps(
                {
                    "reason": "Interpret the current request",
                    "outcomes": [{"reference_mode": "independent", **item} for item in state["outcomes"]],
                }
            )
            return
        state["calls"].append(params)
        if isinstance(first, str) and first.startswith("You operate AI Station"):
            assert state["decisions"], "Unexpected extra controller decision"
            value = dict(state["decisions"].pop(0))
            context = json.loads(params["messages"][1]["content"])
            if not context.get("outcomes"):
                value.setdefault("outcomes", state["outcomes"])
            yield json.dumps(value)
        elif any(
            "proposal_schema" in message["content"]
            for message in params["messages"]
            if isinstance(message["content"], str)
        ):
            yield json.dumps(state["proposal"])
        else:
            yield state["reply"]

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return state


def submit(api, content, **kwargs):
    response = api.post(
        "/api/chat/turns",
        json={
            "client_request_id": str(uuid4()),
            "selection": {"execution_mode": "assistant", "model": "test-model"},
            "execution_mode": "assistant",
            "content": content,
            "web_search": {"enabled": False},
            **kwargs,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def drain():
    # Every tick reopens its session and has a new identity, as after a worker
    # restart. Only persisted graph state may connect the controller rounds.
    for index in range(100):
        with session_factory()() as db:
            if tick(db, "single-controller-slot-" + str(index)) is None:
                return
    raise AssertionError("Controller did not drain")


def root_state(result):
    with session_factory()() as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded", root.error_message
        return root.metadata_json


def failed_root_state(result):
    with session_factory()() as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "failed", root.error_message
        assert "Controller decision failed" in root.error_message
        return root.metadata_json


@pytest.mark.parametrize(
    "content",
    [
        "Wolałbym wersję z szafą stojącą przy oknie",
        "I'd rather have the bicycle resting against a brick wall",
        "Niech ten przedmiot stoi w ogrodzie",
        "Una versión con el armario en un jardín, por favor",
    ],
)
def test_automatic_image_turn_infers_before_dispatch_without_keyword_fallback(model, bridge, content):
    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:1"])
    model["decisions"] = [
        tool(
            "image.recompose",
            instruction="Move the reference wardrobe into a bright garden",
            images=["input:image:1"],
        ),
        finish(1),
    ]
    with TestClient(app) as api:
        source = upload(api)["id"]
        result = submit(api, content, image_artifact_ids=[source])
        assert result["run"]["executor_type"] == "assistant_controller"
        drain()
        state = root_state(result)
        assert [step["tool"] for step in state["controller_steps"]] == ["image.recompose"]
        with session_factory()() as db:
            rows = list(db.scalars(select(Run)))
            assert any(row.capability == "image.recompose" and row.status == "succeeded" for row in rows)
            assert not any(row.capability == "chat.vision" for row in rows)
        assert len(model["calls"]) == 2
        assert len(model["intent_calls"]) == 1
        inferred = json.loads(model["intent_calls"][0]["messages"][1]["content"])
        assert "tools" not in inferred and "argument_types" not in inferred


def test_ordinary_question_uses_streaming_reply_tool_without_media(model):
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An explanation"}]
    model["decisions"] = [tool("chat.reply", instruction="Answer the user's question")]
    with TestClient(app) as api:
        result = submit(api, "Explain how photo editing works; do not create anything")
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        detail = api.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert any(message["content"] == model["reply"] for message in detail["messages"])
        with session_factory()() as db:
            assert not any(row.executor_type == "photo_pipe" for row in db.scalars(select(Run)))


def test_dynamic_research_image_image_agent_chain_binds_actual_results(
    model, bridge, implemented_media, monkeypatch
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
                    "title": "Neutral product design",
                    "url": "https://example.com/design",
                    "snippet": "Oak wardrobes and diffuse daylight",
                }
            ],
            "partial": False,
        }

    monkeypatch.setattr(web_search, "search", search)
    model["outcomes"] = [
        {
            "kind": "image",
            "count": 2,
            "description": "Two sequential image results",
            "reference_mode": "sequential",
        },
        {
            "kind": "agent_draft",
            "count": 1,
            "description": "A reviewed recurring agent draft",
            "agent_media_kind": "avatar",
        },
    ]
    model["proposal"] = {
        "name": "Daily world news avatar",
        "goal": "Create an avatar with the latest world news every 24 hours",
        "tools": ["web_search", "create_media"],
        "search_query": "latest world news",
        "trigger": "interval",
        "interval_seconds": 86400,
        "media": {
            "kind": "avatar",
            "description_source": "goal",
            "request": {"speech_text": "Summarize today's verified world news in Polish"},
        },
    }
    model["decisions"] = [
        tool("web.search", query="Oak wardrobe product design"),
        tool("web.search", query="Oak wardrobe product design"),
        tool(
            "image.generate",
            instruction="Create a neutral oak wardrobe product image inspired by the observed design facts",
            images=[],
        ),
        tool(
            "image.recompose",
            instruction="Place the generated wardrobe in a blue studio",
            images=["step:2:image:1"],
        ),
        tool(
            "agent.create",
            instruction="Prepare a disabled agent that creates an avatar with the latest world news every 24 hours",
        ),
        finish(2, 3, 4),
    ]
    with TestClient(app) as api:
        result = submit(
            api,
            "Research furniture online, create an image, transform that result, then prepare a recurring agent",
            web_search={"enabled": True},
        )
        drain()
        state = root_state(result)
        assert [step["tool"] for step in state["controller_steps"]] == [
            "web.search",
            "image.generate",
            "image.recompose",
            "agent.create",
        ]
        assert all(step["observation"]["status"] == "succeeded" for step in state["controller_steps"])
        first_image = state["controller_steps"][1]["artifacts"][0]["snapshot"]["id"]
        with session_factory()() as db:
            edited = db.scalar(select(Run).where(Run.capability == "image.recompose"))
            assert edited.parameters["parent_artifact_ids"] == [first_image]
            agents = list(db.scalars(select(Agent)))
            assert len(agents) == 1 and not agents[0].enabled
            assert agents[0].media["kind"] == "avatar"
            assert "web_search" in agents[0].tools
            assert (agents[0].trigger == "interval" and agents[0].interval_seconds == 86400) or (
                agents[0].trigger == "cron" and agents[0].cron_expr == "0 0 * * *"
            )
        assert len(model["decisions"]) == 0


@pytest.mark.parametrize(
    "bad",
    [
        tool("web.search", query="not authorized"),
        tool("image.generate", instruction="unrequested mutation", images=[]),
        tool("agent.create", instruction="unrequested persistent agent"),
        tool("artifact.read", artifacts=["/etc/passwd"]),
    ],
)
def test_closed_tools_and_outcome_affordances_reject_unrequested_actions(model, bad):
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An explanation"}]
    model["decisions"] = [bad, bad]
    with TestClient(app) as api:
        result = submit(api, "Explain tools; do not run any action")
        drain()
        assert failed_root_state(result).get("controller_outcome") != "finish"
        with session_factory()() as db:
            assert not list(db.scalars(select(Run).where(Run.run_type == "tool")))
            assert not list(db.scalars(select(Agent)))


def test_generated_result_cannot_be_replaced_with_a_guessed_uuid(model, bridge):
    bad = tool("image.recompose", instruction="New scene", images=[str(uuid4())])
    model["decisions"] = [bad, bad]
    with TestClient(app) as api:
        result = submit(
            api, "A version of the supplied cabinet in a new scene", image_artifact_ids=[upload(api)["id"]]
        )
        drain()
        assert failed_root_state(result).get("controller_outcome") != "finish"
        with session_factory()() as db:
            assert not list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))


def test_two_requested_images_cannot_finish_after_only_one(model, bridge):
    model["outcomes"] = [{"kind": "image", "count": 2, "description": "Two distinct images"}]
    model["decisions"] = [tool("image.generate", instruction="A wardrobe", images=[]), finish(1), finish(1)]
    with TestClient(app) as api:
        result = submit(api, "Create two separate wardrobe images")
        drain()
        state = failed_root_state(result)
        assert state.get("controller_outcome") != "finish"
        assert len(state["controller_steps"]) == 1
        assert state["controller_outcomes"][0]["count"] == 2


def test_declared_outcomes_cannot_be_shrunk_after_a_tool(model, bridge):
    model["outcomes"] = [{"kind": "image", "count": 2, "description": "Two distinct images"}]
    dishonest = {**finish(1), "outcomes": [{"kind": "image", "count": 1, "description": "Only one image"}]}
    model["decisions"] = [tool("image.generate", instruction="A wardrobe", images=[]), dishonest, dishonest]
    with TestClient(app) as api:
        result = submit(api, "Create two separate wardrobe images")
        drain()
        assert failed_root_state(result).get("controller_outcome") != "finish"


def test_failed_tool_is_observed_before_a_different_call_and_streamed_reply(model, monkeypatch):
    from app import web_search

    queries = []

    async def search(query):
        queries.append(query)
        if len(queries) == 1:
            raise ValueError("Synthetic search failure")
        return {"query": query, "sources": [], "partial": True}

    monkeypatch.setattr(web_search, "search", search)
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "A researched answer"}]
    model["decisions"] = [
        tool("web.search", query="first question"),
        tool("web.search", query="different question"),
        tool("chat.reply", instruction="Answer using the actual partial evidence"),
    ]
    with TestClient(app) as api:
        result = submit(api, "Research the question", web_search={"enabled": True})
        drain()
        state = root_state(result)
        assert state["controller_steps"][0]["observation"]["status"] == "failed"
        assert state["controller_steps"][1]["observation"]["status"] == "succeeded"
        context = json.loads(model["calls"][1]["messages"][1]["content"])
        assert context["observations"][0]["status"] == "failed"
        assert queries == ["first question", "different question"]


def test_stop_forwards_across_owned_capability_tasks_and_preserves_unrelated_work(model, bridge):
    from app.runs import create_run, create_task, request_cancel

    model["decisions"] = [tool("image.generate", instruction="Neutral wardrobe", images=[])]
    with TestClient(app) as api:
        result = submit(api, "Create a wardrobe image")
        with session_factory()() as db:
            for _ in range(4):
                assert tick(db, "one-slot") is not None
            root = db.get(Run, result["run"]["id"])
            assert root.status == "waiting_for_tool"
            children = list(db.scalars(select(Run).where(Run.task_id != root.task_id)))
            assert children, "The setup must publish a separately owned capability Task"
            unrelated_task = create_task(db, title="Unrelated", prompt="", capability="test")
            unrelated = create_run(
                db, unrelated_task, run_type="test", capability="test", executor_type="fake"
            )
            request_cancel(db, root)
            db.commit()
            assert root.status == "canceled"
            assert all(db.get(Run, row.id).status == "canceled" for row in children)
            assert unrelated.status == "queued"
        detail = api.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert not any(message["metadata"].get("controller_internal") for message in detail["messages"])


def test_bounded_artifact_read_supplies_actual_content_to_the_next_decision(model):
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "A document answer"}]
    model["decisions"] = [
        tool("artifact.read", artifacts=["input:text:1"]),
        tool("chat.reply", instruction="Explain the attached document"),
    ]
    with TestClient(app) as api:
        result = submit(
            api,
            "Explain the attached note",
            attachments=[{"name": "note.txt", "kind": "text", "content": "The cabinet is made from oak."}],
        )
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        next_context = json.loads(model["calls"][1]["messages"][1]["content"])
        assert "The cabinet is made from oak." in next_context["observations"][0]["tool_data_excerpt"]
        detail = api.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]


def test_database_contention_retries_publication_without_repeating_inference(model, monkeypatch):
    import sqlite3

    from app import assistant_decisions
    from test_worker_database_busy import error

    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An explanation"}]
    model["decisions"] = [tool("chat.reply", instruction="Answer the user")]
    original = assistant_decisions.append_event
    publications = []

    def append(db, run_id, event_type, payload):
        if event_type == "assistant.decision":
            publications.append(run_id)
            if len(publications) == 1:
                raise error(sqlite3.SQLITE_BUSY)
        return original(db, run_id, event_type, payload)

    monkeypatch.setattr(assistant_decisions, "append_event", append)
    with TestClient(app) as api:
        result = submit(api, "Explain orchestration")
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        assert len(publications) == 2 and publications[0] == publications[1]
        assert len(model["calls"]) == 2  # One decision, one actual reply, no replay.


def test_stop_during_decision_closes_inference_and_never_dispatches_tool(model, monkeypatch):
    import asyncio

    from app.runs import request_cancel

    closed = []

    async def stream(self, **params):
        try:
            with session_factory()() as db:
                root = db.scalar(select(Run).where(Run.executor_type == "assistant_controller"))
                request_cancel(db, root)
                db.commit()
            await asyncio.sleep(0.3)
            yield json.dumps(tool("image.generate", instruction="Must not execute", images=[]))
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        result = submit(api, "Create a wardrobe image")
        drain()
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            assert root.status == "canceled"
            assert not list(db.scalars(select(Run).where(Run.run_type == "tool")))
        assert closed == [True]


def test_read_observation_is_not_an_image_outcome():
    from app.assistant_controller import missing_outcomes

    expected = [{"kind": "image", "count": 1, "description": "A changed reference"}]
    observed = [{"tool": "image.describe", "status": "succeeded", "produced_types": ["json", "text"]}]
    assert missing_outcomes(observed, expected)[0]["remaining"] == 1


def test_image_intent_requires_reference_policy_and_rejects_invented_source_aliases():
    from app.assistant_decisions import validate_intent

    context = {"inputs_and_results": [{"alias": "input:image:1"}], "sources": {}}
    value = {
        "reason": "Modify the supplied subject",
        "outcomes": [{"kind": "image", "description": "A version"}],
    }
    with pytest.raises(ValueError, match="Declare whether"):
        validate_intent(json.dumps(value), context)
    value["outcomes"][0].update(reference_mode="provided", source_inputs=["foreign:image:1"])
    with pytest.raises(ValueError, match="supplied input/source aliases"):
        validate_intent(json.dumps(value), context)
    value["outcomes"][0].update(reference_mode="independent", source_inputs=[])
    value["outcomes"].append(
        {
            "kind": "image",
            "description": "A variation of the first result",
            "reference_mode": "sequential",
            "source_inputs": ["hypothetical-future-image"],
        }
    )
    inferred = validate_intent(json.dumps(value), context)
    assert inferred.outcomes[1].source_inputs == []


def test_sequential_images_require_the_previous_result_and_required_pages_must_be_read():
    from app.assistant_controller_tools import image_contract

    context = {
        "outcomes": [
            {"kind": "image", "count": 2, "reference_mode": "sequential", "source_inputs": ["input:source:1"]}
        ],
        "sources": {"input:source:1": "https://example.com"},
        "inputs_and_results": [],
        "observations": [],
    }
    assert image_contract(context)[0] == set()
    context["observations"].append(
        {"index": 1, "tool": "web.read", "status": "succeeded", "arguments": {"sources": ["input:source:1"]}}
    )
    assert image_contract(context)[0] == {"image.generate"}
    context["observations"].append(
        {"index": 2, "tool": "image.generate", "status": "succeeded", "produced_types": ["image"]}
    )
    context["inputs_and_results"] = [
        {"alias": "step:2:image:1", "type": "image", "origin": "current_result", "source_step": 2}
    ]
    allowed, _, previous = image_contract(context)
    assert "image.generate" not in allowed and previous == {"step:2:image:1"}


def test_mixed_image_goals_keep_distinct_reference_policies_without_early_completion():
    from app.assistant_controller import missing_outcomes
    from app.assistant_controller_tools import image_contract
    from app.assistant_decisions import Intent

    goals = Intent.model_validate(
        {
            "reason": "Modify one reference, then create an independent picture",
            "outcomes": [
                {
                    "kind": "image",
                    "description": "An edited reference",
                    "reference_mode": "provided",
                    "source_inputs": ["input:image:1"],
                },
                {
                    "kind": "image",
                    "description": "A new independent picture",
                    "reference_mode": "independent",
                },
            ],
        }
    ).model_dump()["outcomes"]
    context = {
        "outcomes": goals,
        "inputs_and_results": [{"alias": "input:image:1", "type": "image"}],
        "observations": [],
    }
    assert "image.generate" not in image_contract(context)[0]
    context["observations"] = [
        {"index": 1, "tool": "image.recompose", "status": "succeeded", "produced_types": ["image"]}
    ]
    assert len(missing_outcomes(context["observations"], goals)) == 1
    assert image_contract(context)[0] == {"image.generate"}
    context["observations"].append(
        {"index": 2, "tool": "image.generate", "status": "succeeded", "produced_types": ["image"]}
    )
    assert missing_outcomes(context["observations"], goals) == []


def test_provided_image_cannot_be_replaced_with_unrelated_generation(model, bridge):
    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:1"])
    model["decisions"] = [
        tool("image.generate", instruction="An unrelated object", images=[]),
        tool("image.recompose", instruction="Move this object into a garden", images=["input:image:1"]),
        finish(1),
    ]
    with TestClient(app) as api:
        result = submit(api, "Move this object into a garden", image_artifact_ids=[upload(api)["id"]])
        drain()
        assert [step["tool"] for step in root_state(result)["controller_steps"]] == ["image.recompose"]
        with session_factory()() as db:
            photos = list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))
            assert len(photos) == 1 and photos[0].parameters["mode"] == "recompose"


def test_malformed_completion_is_corrected_with_its_rejected_object_without_replaying_media(model, bridge):
    bad = {
        "kind": "finish",
        "reason": "Done",
        "tool": "chat.reply",
        "arguments": {"unrecognized": True},
        "outcomes": [1],
        "response": "Ready",
    }
    model["decisions"] = [tool("image.generate", instruction="A cabinet", images=[]), bad, finish(1)]
    with TestClient(app) as api:
        result = submit(api, "Create a cabinet picture")
        drain()
        assert len(root_state(result)["controller_steps"]) == 1
        correction = model["calls"][-1]["messages"]
        assert correction[-2]["role"] == "assistant" and json.loads(correction[-2]["content"]) == bad
        assert "rejected before dispatch" in correction[-1]["content"]
        with session_factory()() as db:
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))) == 1


def test_completion_uses_real_evidence_and_ignores_non_authoritative_outcome_annotations(model, bridge):
    model["decisions"] = [
        tool("image.generate", instruction="A cabinet", images=[]),
        {**finish(999), "tool": "chat.reply", "outcomes": [999]},
    ]
    with TestClient(app) as api:
        result = submit(api, "Create a cabinet picture")
        drain()
        state = root_state(result)
        assert [step["tool"] for step in state["controller_steps"]] == ["image.generate"]
        with session_factory()() as db:
            decided = db.get(Run, state["decision_run_id"]).metadata_json["decision"]
            assert decided["tool"] is None and decided["outcomes"] == [] and decided["evidence"] == [1]


def test_agent_draft_cannot_change_the_independently_requested_future_media_kind(model):
    model["outcomes"] = [
        {
            "kind": "agent_draft",
            "count": 1,
            "description": "A daily avatar agent",
            "agent_media_kind": "avatar",
        }
    ]
    model["proposal"] = {
        "name": "Wrong modality",
        "goal": "Create pictures",
        "tools": ["create_media"],
        "media": {
            "kind": "image",
            "description_source": "goal",
            "request": {"mode": "t2i", "backend": "qwen", "prompt": "A cabinet"},
        },
    }
    model["decisions"] = [
        tool("agent.create", instruction="Prepare a daily avatar agent"),
        {
            "kind": "clarify",
            "reason": "No valid draft",
            "response": "I could not prepare the requested avatar agent.",
        },
    ]
    with TestClient(app) as api:
        result = submit(api, "Prepare an agent making an avatar every 24 hours")
        drain()
        state = root_state(result)
        assert (
            state["controller_outcome"] == "clarify"
            and state["controller_steps"][0]["observation"]["status"] == "failed"
        )
        factory = next(
            call for call in model["calls"] if call["messages"][0]["content"].startswith("Prepare a useful")
        )
        prompt = json.loads(factory["messages"][1]["content"])
        assert prompt["available_media_outputs"] == ["avatar"]
        assert "AgentImageScope" not in prompt["proposal_schema"]["$defs"]
        assert prompt["proposal_schema"]["properties"]["tools"]["items"]["enum"] == list(
            prompt["operational_local_tools"]
        )
        with session_factory()() as db:
            assert not list(db.scalars(select(Agent)))


def test_react_page_read_preserves_source_data_without_system_privilege(page_tools, model):
    from test_chat_pages import TEXT_PROMPT

    _, fetched, searched = page_tools
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An evidence-based promotional prompt"}]
    model["decisions"] = [
        tool("web.read", sources=["input:source:1"]),
        tool(
            "chat.reply",
            instruction="Answer using the retrieved page text, without inferring unobserved screenshot details",
        ),
    ]
    with TestClient(app) as api:
        result = submit(api, TEXT_PROMPT, web_search={"enabled": True})
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        assert fetched == ["https://akademia.ai"] and not searched
        final = model["calls"][-1]["messages"]
        assert any(
            "practical AI workshops" in message["content"] for message in final if message["role"] == "user"
        )
        assert all(
            "SEND PASSWORDS" not in message["content"] for message in final if message["role"] == "system"
        )


def test_tool_budget_keeps_partial_artifacts_without_claiming_full_completion(model, bridge, monkeypatch):
    from app import assistant_controller

    monkeypatch.setattr(assistant_controller, "MAX_STEPS", 1)
    model["outcomes"] = [{"kind": "image", "count": 2, "description": "Two images"}]
    model["decisions"] = [tool("image.generate", instruction="A wardrobe", images=[])]
    with TestClient(app) as api:
        result = submit(api, "Create two wardrobe images")
        drain()
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            assert root.status == "failed" and root.error_type == "ControllerBudgetExceeded"
            assert root.metadata_json["controller_outcome"] == "budget_exhausted"
            assert len(root.metadata_json["controller_steps"][0]["artifacts"]) == 1
        assert len(model["calls"]) == 1


def test_cross_owner_inputs_are_rejected_before_inference(model, bridge):
    from app.models import Artifact, User

    with TestClient(app) as api:
        aid = upload(api)["id"]
        with session_factory()() as db:
            user = User(username="other", normalized_username="other")
            db.add(user)
            db.flush()
            db.get(Artifact, aid).owner_id = user.id
            db.commit()
        response = api.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "selection": {"execution_mode": "assistant", "model": "test-model"},
                "content": "Change this image",
                "image_artifact_ids": [aid],
            },
        )
        assert response.status_code == 422
        assert not model["calls"]


def test_activity_stays_visible_while_waiting_and_moves_to_the_streamed_reply(model):
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An answer"}]
    model["decisions"] = [tool("chat.reply", instruction="Answer")]
    with TestClient(app) as api:
        result = submit(api, "Explain orchestration")
        path = "/api/chat/conversations/" + result["conversation_id"]
        initial = api.get(path).json()
        assert not initial["messages"][-1]["metadata"]["routing_only"]
        reply_id = None
        for index in range(10):
            with session_factory()() as db:
                tick(db, "reply-publication-" + str(index))
                reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
                if reply is not None:
                    reply_id = reply.id
                    break
        assert reply_id
        pending = api.get(path).json()
        assert pending["active_run"]["id"] == result["run"]["id"]
        assert pending["active_run"]["stream_run_id"] == reply_id
        assistants = [message for message in pending["messages"] if message["role"] == "assistant"]
        assert len(assistants) == 1
        assert assistants[0]["run_id"] == reply_id and assistants[0]["controller_steps"]
        drain()


def test_next_turn_retains_original_attachment_and_labels_generated_result_provenance(model, bridge):
    from app.assistant_controller import decision_context

    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:1"])
    model["decisions"] = [
        tool("image.recompose", instruction="Place the wardrobe in a garden", images=["input:image:1"]),
        finish(1),
    ]
    with TestClient(app) as api:
        source = upload(api)["id"]
        first = submit(api, "A version of the wardrobe in a garden", image_artifact_ids=[source])
        drain()
        followup = api.post(
            "/api/chat/conversations/" + first["conversation_id"] + "/messages",
            json={
                "content": "Now put the original in a studio",
                "execution_mode": "assistant",
                "web_search": {"enabled": False},
            },
        )
        assert followup.status_code == 202, followup.text
        with session_factory()() as db:
            root = db.get(Run, followup.json()["id"])
            entries = decision_context(db, root)["inputs_and_results"]
            assert {entry["origin"] for entry in entries} == {"previous_attachment", "previous_result"}
            output = next(entry for entry in entries if entry["origin"] == "previous_result")
            assert output["source_tool"] == "image.recompose" and output["source_step"] == 1
            saved = root.parameters["controller_inputs"]
            assert any(item["snapshot"]["id"] == source for item in saved)


def test_requested_pixel_inspection_uses_vision_then_a_single_visible_streamed_answer(vision_runtime, model):
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "An actual pixel analysis"}]
    model["decisions"] = [
        tool("image.describe", instruction="Describe the actual colors and shapes", images=["input:image:1"]),
        tool("chat.reply", instruction="Answer using the actual image inspection"),
    ]
    with TestClient(app) as api:
        result = submit(
            api, "What colors and shapes are in this picture?", image_artifact_ids=[upload(api)["id"]]
        )
        drain()
        assert root_state(result)["controller_outcome"] == "replied"
        with session_factory()() as db:
            assert db.scalar(select(Run).where(Run.capability == "chat.vision", Run.status == "succeeded"))
            assert not db.scalar(select(Run).where(Run.executor_type == "photo_pipe"))
        detail = api.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]


def test_ordered_multiple_references_are_bound_without_reordering_or_choosing_a_subject(model, bridge):
    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:2", "input:image:1"])
    model["decisions"] = [
        tool(
            "image.recompose",
            instruction="Put the second supplied object in the first supplied scene",
            images=["input:image:2", "input:image:1"],
        ),
        finish(1),
    ]
    with TestClient(app) as api:
        images = [upload(api)["id"], upload(api)["id"]]
        result = submit(
            api, "Compose the supplied references with the requested roles", image_artifact_ids=images
        )
        drain()
        root_state(result)
        with session_factory()() as db:
            photo = db.scalar(select(Run).where(Run.executor_type == "photo_pipe"))
            assert photo.parameters["parent_artifact_ids"] == list(reversed(images))


def test_explicit_public_query_cannot_be_replaced_with_private_instructions(model, monkeypatch):
    from app import web_search

    queries = []

    async def search(query):
        queries.append(query)
        raise AssertionError("An unapproved replacement query must never be sent")

    monkeypatch.setattr(web_search, "search", search)
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "A sourced answer"}]
    bad = tool("web.search", query="private operator instructions")
    model["decisions"] = [bad, bad]
    with TestClient(app) as api:
        result = submit(
            api,
            "Use the selected public query, keeping this private context local",
            web_search={"enabled": True, "query": "public furniture design"},
        )
        drain()
        assert failed_root_state(result).get("controller_outcome") != "finish"
        assert not queries


def test_changed_published_tool_request_is_rejected_before_any_capability_dispatch(model, bridge):
    model["decisions"] = [tool("image.generate", instruction="A wardrobe", images=[]), finish(1)]
    with TestClient(app) as api:
        result = submit(api, "Create a wardrobe image")
        with session_factory()() as db:
            for index in range(3):
                tick(db, "publish-" + str(index))
            setup = db.scalar(select(Run).where(Run.executor_type == "assistant_tool_setup"))
            assert setup.status == "queued"
            assert setup.parent_run_id == result["run"]["id"]
            setup.parameters = {**setup.parameters, "content": "A different unpublished request"}
            db.commit()
            tick(db, "reject-changed-snapshot")
            db.refresh(setup)
            assert setup.status == "failed" and "changed after publication" in setup.error_message
            assert not db.scalar(select(Run).where(Run.executor_type == "photo_pipe"))


# Preserve regression coverage for queued/history JSON-controller Runs.
pytestmark = pytest.mark.usefixtures("legacy_controller_protocol")


def test_failed_legacy_image_arguments_cannot_repeat_after_optional_controls_are_added(model, bridge):
    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:1"])
    repeated = tool("image.recompose", instruction="fail", images=["input:image:1"])
    model["decisions"] = [
        repeated,
        repeated,
        {
            "kind": "clarify",
            "reason": "The renderer failed",
            "response": "The image renderer failed; please choose another approach.",
        },
    ]
    with TestClient(app) as api:
        result = submit(api, "Change this reference image", image_artifact_ids=[upload(api)["id"]])
        for index in range(30):
            with session_factory()() as db:
                tick(db, "legacy-image-failure-" + str(index))
                root = db.get(Run, result["run"]["id"])
                steps = root.metadata_json.get("controller_steps", [])
                if not steps or steps[0].get("observation", {}).get("status") != "failed":
                    continue
                steps = json.loads(json.dumps(steps))
                for key in ("reference_layout", "reference_strength"):
                    steps[0]["arguments"].pop(key, None)
                root.metadata_json = {**root.metadata_json, "controller_steps": steps}
                for decision in db.scalars(
                    select(Run).where(
                        Run.parent_run_id == root.id,
                        Run.executor_type == "assistant_decision",
                        Run.status == "queued",
                    )
                ):
                    context = json.loads(json.dumps(decision.parameters["decision_context"]))
                    for observed in context["observations"]:
                        for key in ("reference_layout", "reference_strength"):
                            observed["arguments"].pop(key, None)
                    decision.parameters = {**decision.parameters, "decision_context": context}
                db.commit()
                break
        else:
            raise AssertionError("The failed image was not observed")
        drain()
        assert len(root_state(result)["controller_steps"]) == 1
        with session_factory()() as db:
            assert len(list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))) == 1
