from uuid import uuid4

import pytest
from app.api import app
from app.assistant import AssistantExecutor
from app.chat import MessageBody
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Message, Project, Run, Task, Worktree
from app.project_reference import resolve_project_reference
from app.providers import ProviderError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def project(session, name="Weather Station"):
    row = Project(name=name, repo_path="/allowed/weather", agent_rules="Preserve existing APIs")
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize(
    "prompt",
    [
        'In project "Weather Station": implement a temperature chart',
        "in the project Weather Station, fix the refresh button",
        "Dodaj wykres w projekcie Weather Station",
        "W projekcie „Weather Station”: napraw testy",
        "Dla projektu 'Weather Station': zbuduj panel",
        "Fix tests in project Weather Station.",
    ],
)
def test_explicit_project_change_selects_local_auto_with_revision(session, prompt):
    saved = project(session)
    original = MessageBody(content=prompt)
    body, reference = resolve_project_reference(session, original, "work")
    assert original.coding is None
    assert str(body.coding.project_id) == saved.id
    assert body.coding.expected_updated_at == saved.updated_at
    assert body.coding.model == "auto" and body.coding.explore
    assert not body.coding.external_ai and body.coding.files == []
    assert reference["project_name"] == saved.name
    assert reference["source"] == "current_instruction"


@pytest.mark.parametrize(
    "prompt,updates,mode",
    [
        ("Explain how to fix tests in project Weather Station", {}, "work"),
        ("In project Weather Station: what is the architecture?", {}, "work"),
        ("In project Weather Station", {}, "work"),
        ("Do not fix tests in project Weather Station", {}, "work"),
        ("Fix tests in project Weather Station", {}, "chat"),
        ("Fix tests in project Weather Station", {}, "local"),
        ("Fix tests in project Weather Station", {"action": "chat"}, "work"),
        ("Fix tests in project Weather Station with Cursor", {}, "work"),
        ("Fix tests in project Weather Station using Codex", {}, "work"),
        ("Fix tests in project Weather Station", {"image_artifact_ids": [str(uuid4())]}, "work"),
        ("Fix tests in project Weather Station", {"web_search": {"enabled": True}}, "work"),
        (
            "Fix tests in project Weather Station",
            {"attachments": [{"name": "a.txt", "content": "Use this project", "kind": "text"}]},
            "work",
        ),
        (
            "Fix tests in project Weather Station",
            {"continuation": {"task_id": str(uuid4()), "expected_run_id": str(uuid4())}},
            "work",
        ),
    ],
)
def test_discussion_chat_media_and_explicit_context_do_not_acquire_project_scope(
    session, prompt, updates, mode
):
    project(session)
    original = MessageBody(content=prompt, **updates)
    body, reference = resolve_project_reference(session, original, mode)
    assert body is original and reference is None


@pytest.mark.parametrize(
    "names,prompt,status",
    [
        (["Weather Station", "weather station"], "Fix tests in project Weather Station", 409),
        (["Weather Station", "Other"], "Fix in project Weather Station, and in project Other", 409),
        (["Weather"], "Fix tests in project Weather Station", 422),
        (["Weather Station"], "Fix tests in project Weather Station2", 422),
        (["Weather Station"], "Fix tests in project Unknown", 422),
    ],
)
def test_ambiguous_unknown_or_partial_names_do_not_publish_work(session, names, prompt, status):
    for name in names:
        project(session, name)
    with pytest.raises(HTTPException) as caught:
        resolve_project_reference(session, MessageBody(content=prompt), "work")
    assert caught.value.status_code == status
    assert session.scalar(select(func.count()).select_from(Run)) == 0


@pytest.fixture
def auto_model(monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])
    monkeypatch.setattr(
        "app.coding_model_routing.select_coding_model",
        lambda _: {"model": "test-model", "context_size": 131072, "gpus": [2, 7]},
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError("Deterministic project routing must not contact a model")

    monkeypatch.setattr(AssistantExecutor, "plan", forbidden)
    monkeypatch.setattr(LocalChatProvider, "stream", forbidden)


def turn(prompt="W projekcie Weather Station: napraw testy"):
    return {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "work", "model": "test-model"},
        "content": prompt,
    }


def step():
    with session_factory()() as session:
        return tick(session, "project-reference-test")


def test_first_send_freezes_project_and_replays_after_registry_change(auto_model):
    with session_factory()() as session:
        saved = project(session)
        session.commit()
        project_id, revision = saved.id, saved.updated_at
    body = turn()
    with TestClient(app) as client:
        response = client.post("/api/chat/turns", json=body)
        assert response.status_code == 202, response.text
        receipt = response.json()
        with session_factory()() as session:
            run = session.get(Run, receipt["run"]["id"])
            assert run.parameters["coding"]["model"] == "auto"
            assert run.parameters["coding"]["project_id"] == project_id
            assert run.effective_permissions == ["manage_agents"]
            user = session.get(Message, receipt["user_message_id"])
            assert user.metadata_json["project_reference"]["project_name"] == "Weather Station"
            assert session.scalar(select(func.count()).select_from(Worktree)) == 0
        assert step() == receipt["run"]["id"]
        detail = client.get(f"/api/chat/conversations/{receipt['conversation_id']}").json()
        child = detail["active_run"]
        assert child["executor_type"] == "worktree_prepare"
        assert child["project_id"] == project_id and child["task_id"] == receipt["task_id"]
        request = child["parameters"]["local_coding"]
        assert request["explore"] and request["files"] == []
        assert request["model_selection"]["requested"] == "auto"
        assert request["model_selection"]["context_size"] >= 100000
        assert request["guidance"] == "Preserve existing APIs"
        assert "Weather Station" in detail["messages"][-1]["content"]
        with session_factory()() as session:
            saved = session.get(Project, project_id)
            saved.name = "Renamed"
            saved.updated_at = utcnow()
            assert saved.updated_at != revision
            session.commit()
        reset_engine()
        replay = client.post("/api/chat/turns", json=body)
        assert replay.status_code == 202
        assert replay.json()["run"]["id"] == receipt["run"]["id"]
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            assert session.scalar(select(func.count()).select_from(Worktree)) == 1
        stop = client.post(f"/api/coding/sessions/{receipt['task_id']}/cancel")
        assert stop.status_code == 200, stop.text
        assert client.get(f"/api/runs/{child['id']}").json()["status"] == "canceled"


@pytest.mark.parametrize("failure", ["revision", "no_model", "canceled"])
def test_stale_project_no_fitting_model_and_stop_do_not_create_worktree(auto_model, monkeypatch, failure):
    with session_factory()() as session:
        saved = project(session)
        session.commit()
        project_id = saved.id
    with TestClient(app) as client:
        response = client.post("/api/chat/turns", json=turn())
        assert response.status_code == 202, response.text
        receipt = response.json()
        if failure == "revision":
            with session_factory()() as session:
                session.get(Project, project_id).updated_at = utcnow()
                session.commit()
        elif failure == "no_model":

            def unavailable(_):
                raise ProviderError("No fitting 100k context model")

            monkeypatch.setattr("app.coding_model_routing.select_coding_model", unavailable)
        else:
            assert client.post(f"/api/runs/{receipt['run']['id']}/cancel").status_code == 200
        step()
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Worktree)) == 0
            assert session.scalar(select(func.count()).select_from(Run)) == 1
        detail = client.get(f"/api/chat/conversations/{receipt['conversation_id']}").json()
        assert detail["active_run"] is None
        if failure != "canceled":
            assert ("settings changed" if failure == "revision" else "No fitting 100k") in detail["messages"][
                -1
            ]["content"]


def test_ambiguous_first_send_rolls_back_conversation_and_receipt(auto_model):
    with session_factory()() as session:
        project(session)
        project(session)
        session.commit()
    with TestClient(app) as client:
        response = client.post("/api/chat/turns", json=turn())
        assert response.status_code == 409
        assert client.get("/api/chat/conversations").json() == []
        with session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 0


def test_explicit_project_scope_wins_over_a_name_in_the_prompt(session):
    named = project(session)
    selected = project(session, "Selected project")
    original = MessageBody(
        content=f"Fix tests in project {named.name}",
        coding={
            "project_id": selected.id,
            "expected_updated_at": selected.updated_at,
            "explore": True,
            "model": "test-model",
        },
    )
    body, reference = resolve_project_reference(session, original, "work")
    assert body is original and str(body.coding.project_id) == selected.id
    assert reference is None


def test_overlapping_names_and_regex_punctuation_match_exact_project(session):
    project(session, "Weather")
    selected = project(session, "Weather (v2).ai")
    body, _ = resolve_project_reference(
        session, MessageBody(content='In project "Weather (v2).ai": add tests'), "work"
    )
    assert str(body.coding.project_id) == selected.id


def test_auto_coding_does_not_snapshot_or_start_the_conversation_model(auto_model, monkeypatch):
    from app import assistant as assistant_module

    def forbidden(*args):
        raise AssertionError("Local Auto coding cannot use or share with the conversation provider")

    monkeypatch.setattr(assistant_module, "snapshot_provider", forbidden)
    with session_factory()() as session:
        project(session)
        session.commit()
    with TestClient(app) as client:
        response = client.post("/api/chat/turns", json=turn())
        assert response.status_code == 202, response.text
        assert "external_ai" not in response.json()["run"]["effective_permissions"]
        step()
        with session_factory()() as session:
            assert set(session.scalars(select(Run.executor_type))) == {"orchestrator", "worktree_prepare"}
