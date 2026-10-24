"""Reviewed sources and their offline follow-ups stay bound to one conversation."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.conversation_data_schema import DataResearchSelection, DataScope
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Agent, Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_research_data import sources as sources
from test_data_output_files import chart
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def start(api, state, research, mode="chat"):
    response = api.post("/api/chat/conversations", json={"model": "external-unused", "execution_mode": mode})
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    response = api.post(
        "/api/chat/conversations/" + cid + "/messages",
        json={
            "content": "Calculate totals from the reviewed public JSON observations",
            "data": {"model": state["model"], "research": research},
        },
    )
    assert response.status_code == 202, response.text
    return cid, response.json()


def drain():
    for _ in range(30):
        with session_factory()() as s:
            if tick(s, "conversation-public-data") is None:
                return
    raise AssertionError("Queue did not drain")


def runs(task):
    with session_factory()() as s:
        return list(s.scalars(select(Run).where(Run.task_id == task).order_by(Run.created_at, Run.id)))


def test_typed_sources_preserve_legacy_serialization_and_file_requirements():
    aid = str(uuid4())
    assert DataScope(input_artifact_ids=[aid]).model_dump(mode="json") == {
        "input_artifact_ids": [aid],
        "max_repairs": 1,
        "model": "auto",
        "maximum_runtime": 600,
    }
    for value in [
        {},
        {"input_artifact_ids": []},
        {"research": {}},
        {"research": {"read_search_pages": True}},
        {"research": {"fetch_urls": ["http://127.0.0.1/"]}},
        {"research": {"search_query": "public", "tools": ["shell"]}},
        {
            "research": {"fetch_urls": ["https://data.example.com/"]},
            "input_artifact_ids": [str(uuid4()) for _ in range(8)],
        },
    ]:
        with pytest.raises(ValueError):
            DataScope.model_validate(value)
    assert DataResearchSelection(
        search_query="public", read_search_pages=True, fetch_urls=["https://data.example.com/"]
    ).tools() == ["web_search", "search_pages", "http_fetch"]


@pytest.mark.parametrize(
    "research",
    [
        {"fetch_urls": ["https://data.example.com/numbers"]},
        {"search_query": "public numbers", "read_search_pages": True},
        {
            "search_query": "public numbers",
            "read_search_pages": True,
            "fetch_urls": ["https://data.example.com/numbers"],
        },
    ],
)
def test_conversation_sources_use_existing_pipeline_and_inspected_capture_without_an_agent(
    data_environment, sources, research
):
    with TestClient(app) as api:
        cid, parent = start(api, data_environment, research)
        drain()
        rows = runs(parent["task_id"])
        assert all(row.status == "succeeded" for row in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert all(row.agent_id is None and row.conversation_id == cid for row in rows)
        source = next(r for r in rows if r.executor_type == "agent_page_coding")
        inspection = next(r for r in rows if r.executor_type == "data_inspection")
        assert (
            inspection.parent_run_id == source.id
            and inspection.parameters["agent_coding_deadline"] == source.parameters["agent_coding_deadline"]
        )
        python = next(r for r in rows if r.executor_type == "python")
        assert len(python.parameters["inputs"]) == 1 and "network_read" not in python.effective_permissions
        with session_factory()() as s:
            snapshot = s.get(Artifact, python.parameters["inputs"][0]["artifact_id"])
            assert snapshot.metadata_json["data_inspection_run_id"] == inspection.id
            assert inspection.metadata_json["data_preview"]["format"] == "json"
            assert not list(s.scalars(select(Agent)))
        detail = api.get("/api/chat/conversations/" + cid).json()
        assert detail["messages"][-1]["task_status"] == "succeeded"


def test_natural_followups_reuse_captured_json_without_research_even_after_original_expiry(
    data_environment, sources, monkeypatch
):
    data_environment.update(data_exports=1, exports={"chart.png": chart()})
    with TestClient(app) as api:
        cid, parent = start(api, data_environment, {"fetch_urls": ["https://data.example.com/numbers"]})
        drain()
        first = runs(parent["task_id"])
        original = next(r for r in first if r.executor_type == "python").parameters["inputs"]
        with monkeypatch.context() as clock:
            clock.setattr("app.conversation_data.utcnow", lambda: utcnow() + timedelta(days=1))
            response = api.post(
                "/api/chat/conversations/" + cid + "/messages",
                json={"content": "Create a chart from those data"},
            )
        assert response.status_code == 202, response.text
        second = response.json()
        assert second["task_id"] != parent["task_id"]
        assert "research" not in second["parameters"]["data"]
        assert second["parameters"]["data"]["input_artifact_ids"] == [original[0]["artifact_id"]]
        assert (
            second["parameters"]["data_reference"]["captured_sources"][0]["artifact_id"]
            == original[0]["artifact_id"]
        )
        drain()
        rows = runs(second["task_id"])
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert not any(r.executor_type in {"agent_tool", "agent_page_coding"} for r in rows)
        assert next(r for r in rows if r.executor_type == "python").parameters["inputs"] == original
        generation = next(r for r in rows if r.executor_type == "agent_data_generate")
        request = json.loads(generation.parameters["messages"][1]["content"])
        assert "research" not in request
        captured = request["inputs"][0]
        assert captured["source_capture"] is True
        assert captured["source_preview"]["full_source_in_input_file"] is True
        assert captured["source_preview"]["observations"][0]["result"]["pages"][0]["text"]
        assert sources["fetch"] == ["https://data.example.com/numbers"]
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages", json={"content": "Now compare those observations"}
        )
        assert response.status_code == 202, response.text
        drain()
        assert sources["fetch"] == ["https://data.example.com/numbers"]


@pytest.mark.parametrize(
    "change", ["definition", "message_scope", "permission", "deadline", "manifest", "task", "conversation"]
)
def test_conversation_research_scope_tampering_stops_before_public_reads(data_environment, sources, change):
    from app.models import Message
    from app.runs import create_task

    with TestClient(app) as api:
        _, parent = start(api, data_environment, {"fetch_urls": ["https://data.example.com/numbers"]})
        for _ in range(8):
            with session_factory()() as s:
                source = s.scalar(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_tool")
                )
                if source:
                    sid = source.id
                    break
                assert tick(s, "before-conversation-fetch")
        else:
            raise AssertionError("No queued source")
        with session_factory()() as s:
            source = s.get(Run, sid)
            workflow = s.get(Run, source.parent_run_id)
            root = s.get(Run, parent["id"])
            if change == "definition":
                source.parameters = {
                    **source.parameters,
                    "definition": {
                        **source.parameters["definition"],
                        "fetch_urls": ["https://other.example.com/"],
                    },
                }
            elif change == "message_scope":
                message = s.get(Message, root.parameters["user_message_id"])
                message.metadata_json = {
                    **message.metadata_json,
                    "data_scope": {
                        **message.metadata_json["data_scope"],
                        "research": {"fetch_urls": ["https://other.example.com/"]},
                    },
                }
            elif change == "permission":
                source.effective_permissions = [*source.effective_permissions, "external_ai"]
            elif change == "deadline":
                source.parameters = {**source.parameters, "deadline_at": "2099-01-01T00:00:00+00:00"}
            elif change == "manifest":
                workflow.metadata_json = {**workflow.metadata_json, "child_run_ids": []}
            elif change == "task":
                source.task_id = create_task(
                    s, title="Other", prompt="No research grant", capability="test"
                ).id
            elif change == "conversation":
                source.conversation_id = None
            s.commit()
        drain()
        with session_factory()() as s:
            assert s.get(Run, sid).status == "failed"
        assert (
            not sources["fetch"]
            and not sources["search"]
            and data_environment["calls"] == 0
            and not data_environment["jobs"]
        )


@pytest.mark.parametrize("change", ["snapshot", "source", "preview", "lineage", "origin", "inspection"])
def test_followup_refuses_changed_captured_sources_before_additional_execution(
    data_environment, sources, change
):
    from app.config import get_settings

    with TestClient(app) as api:
        cid, parent = start(api, data_environment, {"fetch_urls": ["https://data.example.com/numbers"]})
        drain()
        first = runs(parent["task_id"])
        python = next(r for r in first if r.executor_type == "python")
        with session_factory()() as s:
            snapshot = s.get(Artifact, python.parameters["inputs"][0]["artifact_id"])
            inspection = s.get(Run, snapshot.metadata_json["data_inspection_run_id"])
            source = next(r for r in first if r.executor_type == "agent_tool")
            source_artifact = s.get(Artifact, source.metadata_json["observation"]["artifact_id"])
            if change in {"snapshot", "source", "preview"}:
                artifact = (
                    snapshot
                    if change == "snapshot"
                    else source_artifact
                    if change == "source"
                    else s.get(Artifact, inspection.metadata_json["preview_artifact_id"])
                )
                (get_settings().data_dir / artifact.relative_path).write_text('{"changed":true}')
            elif change == "lineage":
                snapshot.parent_artifact_ids = []
            elif change == "origin":
                snapshot.run_id = None
            elif change == "inspection":
                inspection.status = "failed"
            s.commit()
            before = list(s.scalars(select(Run.id)))
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={"content": "Calculate a total from those data"},
        )
        if change == "preview":
            # Metadata selection is cheap; the worker verifies actual preview
            # bytes before creating a workspace or contacting the model.
            assert response.status_code == 202, response.text
            drain()
            failed = runs(response.json()["task_id"])
            assert len(failed) == 1 and failed[0].status == "failed"
        else:
            assert response.status_code == 422, response.text
            with session_factory()() as s:
                assert list(s.scalars(select(Run.id))) == before
        assert (
            len(sources["fetch"]) == 1
            and data_environment["calls"] == 1
            and len(data_environment["jobs"]) == 1
        )


def test_explicit_refresh_captures_new_sources_without_replacing_old_inputs(data_environment, sources):
    from app.config import get_settings

    with TestClient(app) as api:
        research = {"fetch_urls": ["https://data.example.com/numbers"]}
        cid, parent = start(api, data_environment, research)
        drain()
        first = next(r for r in runs(parent["task_id"]) if r.executor_type == "python").parameters["inputs"][
            0
        ]
        with session_factory()() as s:
            original = (
                get_settings().data_dir / s.get(Artifact, first["artifact_id"]).relative_path
            ).read_bytes()
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={
                "content": "Refresh public observations and calculate the total",
                "data": {"model": data_environment["model"], "research": research},
            },
        )
        assert response.status_code == 202, response.text
        second = response.json()
        drain()
        rows = runs(second["task_id"])
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        refreshed = next(r for r in rows if r.executor_type == "python").parameters["inputs"][0]
        assert refreshed["artifact_id"] != first["artifact_id"] and len(sources["fetch"]) == 2
        with session_factory()() as s:
            assert (
                get_settings().data_dir / s.get(Artifact, first["artifact_id"]).relative_path
            ).read_bytes() == original


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_explicit_current_public_data_instruction_routes_without_an_agent_or_planner(
    data_environment, sources, mode
):
    from app import coding_model_routing
    from app.project_setup import ProjectAutomation

    # Auto selection is fake here; the normal execution and source grants remain real.
    original = coding_model_routing.select_coding_model
    coding_model_routing.select_coding_model = lambda session: {"model": data_environment["model"]}
    try:
        with TestClient(app) as api:
            response = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": mode})
            cid = response.json()["id"]
            response = api.post(
                "/api/chat/conversations/" + cid + "/messages",
                json={
                    "content": "Calculate a total from JSON at https://data.example.com/numbers",
                    "web_search": {"enabled": True},
                    **(
                        {
                            "project_defaults": ProjectAutomation(
                                auto_install_dependencies=True, auto_validate=True
                            ).model_dump()
                        }
                        if mode == "work"
                        else {}
                    ),
                },
            )
            assert response.status_code == 202, response.text
            parent = response.json()
            assert (
                parent["parameters"]["data"]["research"]["fetch_urls"] == ["https://data.example.com/numbers"]
                and parent["parameters"].get("project_defaults") is None
            )
            drain()
            rows = runs(parent["task_id"])
            assert all(r.status == "succeeded" for r in rows), [
                (r.executor_type, r.status, r.error_message) for r in rows
            ]
            assert sources["fetch"] == ["https://data.example.com/numbers"] and data_environment["calls"] == 1
    finally:
        coding_model_routing.select_coding_model = original


@pytest.mark.parametrize(
    "content,enabled",
    [
        ("Calculate totals from JSON at https://data.example.com/numbers", False),
        ("Analyse the design of https://data.example.com/numbers and suggest an image prompt", True),
        ('Explain this example: "calculate totals from JSON at https://data.example.com/numbers"', True),
    ],
)
def test_availability_and_quoted_or_design_text_do_not_select_data_execution(content, enabled):
    from app.chat import MessageBody
    from app.conversation_data import prepare_turn

    body = MessageBody(content=content, web_search={"enabled": enabled})
    assert prepare_turn(body, mode="chat").data is None


@pytest.mark.parametrize("before", ["agent_tool", "data_inspection", "agent_data_generate"])
def test_stop_covers_research_capture_inspection_and_generation(data_environment, sources, before):
    with TestClient(app) as api:
        cid, parent = start(api, data_environment, {"fetch_urls": ["https://data.example.com/numbers"]})
        for _ in range(16):
            with session_factory()() as s:
                waiting = s.scalar(
                    select(Run).where(
                        Run.task_id == parent["task_id"], Run.executor_type == before, Run.status == "queued"
                    )
                )
                if waiting:
                    break
                assert tick(s, "before-stop-public-data")
        assert waiting is not None
        response = api.post("/api/chat/conversations/" + cid + "/tasks/" + parent["task_id"] + "/cancel")
        assert response.status_code == 200, response.text
        drain()
        assert not data_environment["calls"] and not data_environment["jobs"]
        assert bool(sources["fetch"]) == (before != "agent_tool")
        assert api.get("/api/runs/" + waiting.id).json()["status"] == "canceled"


def test_confirmed_python_failure_repairs_without_repeating_sources_or_capture(data_environment, sources):
    data_environment["program_failures"] = 1
    with TestClient(app) as api:
        _, parent = start(api, data_environment, {"fetch_urls": ["https://data.example.com/numbers"]})
        drain()
        rows = runs(parent["task_id"])
        jobs = [r for r in rows if r.executor_type == "python"]
        assert len(jobs) == 2 and jobs[0].status == "failed" and jobs[1].status == "succeeded"
        assert (
            jobs[0].parameters["inputs"] == jobs[1].parameters["inputs"]
            and jobs[0].parameters["agent_coding_deadline"] == jobs[1].parameters["agent_coding_deadline"]
        )
        assert (
            len([r for r in rows if r.executor_type == "data_inspection"]) == 1 and len(sources["fetch"]) == 1
        )
        assert (
            next(r for r in reversed(rows) if r.metadata_json.get("data_result")).metadata_json[
                "data_result"
            ]["attempt"]
            == 1
        )


def test_public_data_first_send_receipt_replays_but_changed_sources_conflict(data_environment, sources):
    body = {
        "client_request_id": str(uuid4()),
        "selection": {"provider": "local-openai-compatible", "model": "unused", "execution_mode": "chat"},
        "content": "Calculate a total from reviewed public JSON",
        "data": {
            "model": data_environment["model"],
            "research": {"fetch_urls": ["https://data.example.com/numbers"]},
        },
    }
    with TestClient(app) as api:
        first = api.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        second = api.post("/api/chat/turns", json=body)
        assert second.status_code == 202 and second.json() == first.json()
        conflict = api.post(
            "/api/chat/turns",
            json={
                **body,
                "data": {**body["data"], "research": {"fetch_urls": ["https://other.example.com/"]}},
            },
        )
        assert conflict.status_code == 409, conflict.text
        drain()
        assert sources["fetch"] == ["https://data.example.com/numbers"] and data_environment["calls"] == 1


def test_dataset_words_in_a_url_do_not_select_an_analysis_tool():
    from app.chat import MessageBody
    from app.conversation_data import prepare_turn

    body = MessageBody(
        content="Compare the visual design of https://data.example.com/prices.json and suggest a layout",
        web_search={"enabled": True},
    )
    assert prepare_turn(body, mode="work").data is None


def test_manual_query_only_keeps_its_existing_chat_authority():
    from app.chat import MessageBody
    from app.conversation_data import prepare_turn

    body = MessageBody(
        content="Calculate the average from those data", web_search={"enabled": True, "query": "public data"}
    )
    result = prepare_turn(body, mode="chat")
    assert result.data is None and result.web_search.query == "public data"


def test_explicit_browser_reading_is_not_downgraded_to_plain_http_data():
    from app.chat import MessageBody
    from app.conversation_data import prepare_turn

    body = MessageBody(
        content="Calculate totals from JSON at https://data.example.com/numbers",
        web_search={"enabled": True, "render_pages": True},
    )
    selected = prepare_turn(body, mode="chat")
    assert selected.data is None and selected.web_search.render_pages


@pytest.mark.parametrize("bound", [True, False])
def test_natural_public_analysis_respects_the_bound_work_context(data_environment, sources, bound):
    from app.chat import MessageBody
    from app.conversation_data_reference import resolve
    from app.models import ChatWorkContext, Conversation
    from app.runs import create_task

    with TestClient(app) as api:
        created = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": "work"})
        assert created.status_code == 201
        cid = created.json()["id"]
        with session_factory()() as s:
            task = create_task(
                s,
                title="Existing workspace task",
                prompt="Preserve this active work selection",
                capability="coding.local",
                conversation_id=cid,
            )
            s.add(ChatWorkContext(conversation_id=cid, task_id=task.id if bound else None))
            s.flush()
            body = MessageBody(
                content="Calculate totals from JSON at https://data.example.com/numbers",
                web_search={"enabled": True},
            )
            selected, reference = resolve(s, s.get(Conversation, cid), body, "work")
            if bound:
                assert selected is body and selected.data is None
            else:
                assert selected.data.research.fetch_urls == ["https://data.example.com/numbers"]
            assert reference is None
        assert not sources["fetch"] and not data_environment["calls"]


def test_captured_preview_shows_response_values_beyond_the_generic_json_cell_prefix():
    from app.data_json_preview import inspect_json
    from app.data_research import captured_preview

    values = [
        {
            "url": "https://api.example.com/" + asset + "-USD/spot",
            "text": json.dumps({"data": {"base": asset, "amount": amount}}),
        }
        for asset, amount in [("BTC", "80809.255"), ("ETH", "2379.325")]
    ]
    observations = [
        {
            "tool": "http_fetch",
            "result": {"urls": [p["url"] for p in values], "pages": values, "partial": True},
        }
    ]
    generic = inspect_json(json.dumps({"observations": observations}).encode(), lambda: None)
    assert "80809.255" not in generic["sheets"][0]["preview"][0][1]
    preview = captured_preview(observations)
    pages = preview["observations"][0]["result"]["pages"]
    assert [json.loads(p["text"])["data"]["amount"] for p in pages] == ["80809.255", "2379.325"]
    assert preview["excerpted"] is True
    assert preview["full_source_in_input_file"] is True
    assert preview["observations"][0]["result"]["partial"] is True


def test_captured_preview_stays_small_for_multiple_long_unicode_sources():
    from app.data_research import captured_preview

    observations = [
        {
            "tool": tool,
            "result": {
                key: [{"url": "https://example.com/" + "ą" * 1000, field: "ź" * 1000} for _ in range(3)]
            },
        }
        for tool, key, field in [
            ("web_search", "sources", "snippet"),
            ("search_pages", "pages", "text"),
            ("http_fetch", "pages", "text"),
        ]
    ]
    preview = captured_preview(observations)
    assert len(json.dumps(preview, ensure_ascii=False).encode()) <= 2048
    assert [o["tool"] for o in preview["observations"]] == ["web_search", "search_pages", "http_fetch"]
