"""A model-selected website expectation constrains the existing owned build path."""

# Reused disposable native project fixtures retain their public names.
# ruff: noqa: F811
import pytest
from app.api import app
from app.assistant_controller_tools import TOOLS
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.project_build import ProjectBuildScope
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_projects import local_coding_bridge, owned_runner, repository  # noqa: F401


def test_optional_website_contract_preserves_ordinary_project_serialization():
    assert "output_contract" not in ProjectBuildScope(name="Ordinary app").model_dump()
    args = TOOLS["project.create_code"].arguments.model_validate(
        {"name": "Public site", "instruction": "Build a working site", "output_contract": "static_site"}
    )
    assert args.output_contract == "static_site"
    for scope in [
        {"output_contract": "static_site"},
        {"output_contract": "static_site", "auto_validate": True, "executor": "cursor", "external_ai": True},
        {"output_contract": "unrestricted", "auto_validate": True},
    ]:
        with pytest.raises(ValidationError):
            ProjectBuildScope(name="Invalid scope", **scope)


def test_existing_project_build_freezes_website_validation_through_worktree_handoff(
    repository,
    owned_runner,
    local_coding_bridge,
    monkeypatch,
):
    async def forbidden(self, **params):
        raise AssertionError("Explicit typed build scope does not need a routing inference")
        yield ""

    monkeypatch.setattr(LocalChatProvider, "stream", forbidden)
    original = (repository / "README.md").read_bytes()
    with TestClient(app) as client:
        cid = client.post(
            "/api/chat/conversations", json={"model": "fixture-local", "execution_mode": "orchestrator"}
        ).json()["id"]
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "action": "project.create_code",
                "content": "Build a working public website from the reviewed information",
                "new_project": {
                    "name": "Website output test",
                    "executor": "local",
                    "output_contract": "static_site",
                    "auto_validate": True,
                },
            },
        )
        assert response.status_code == 202, response.text
        for identity in ("dispatch", "setup", "prepare"):
            with session_factory()() as session:
                assert tick(session, "website-" + identity)
        runs = client.get("/api/runs", params={"conversation_id": cid}).json()
        proposal = next(r for r in runs if r["executor_type"] == "local_proposal")
        assert proposal["status"] == "queued"
        params = proposal["parameters"]
        assert params["output_contract"] == "static_site"
        assert params["project_check_policy"]["auto_validate"] is True
        assert params["project_check_policy"]["auto_install_dependencies"] is False
        from app.static_site import commands

        assert params["commands"] == commands()
        assert "src/index.html" in params["guidance"]
        assert params["worktree_run_id"] == proposal["parent_run_id"]
        assert not local_coding_bridge["requests"]
        assert (repository / "README.md").read_bytes() == original


@pytest.mark.parametrize("contract", [None, "static_site"])
def test_react_build_arguments_bind_fixed_local_checked_scope(session, monkeypatch, contract):
    from types import SimpleNamespace

    from app import assistant_controller_tools as tools

    root = SimpleNamespace(
        id="controller",
        parameters={
            "controller_request": {"model": "conversation-model", "web_search": {"enabled": False}},
            "controller_provider": {"location": "local"},
        },
        metadata_json={"controller_steps": []},
    )
    monkeypatch.setattr(tools, "catalog", lambda *_: {})
    args = {"name": "New implementation", "instruction": "Create the requested working deliverable"}
    if contract:
        args["output_contract"] = contract
    params = tools.wrapper_parameters(session, root, "project.create_code", args)
    scope = ProjectBuildScope.model_validate(params["new_project"])
    assert scope.executor == "local" and scope.model == "auto" and not scope.external_ai
    assert not scope.auto_install_dependencies
    if contract:
        assert scope.output_contract == contract and scope.auto_validate and scope.max_repair_attempts == 1
    else:
        assert scope.output_contract is None and not scope.auto_validate and scope.max_repair_attempts == 0


def test_empty_project_cannot_fulfill_a_requested_implementation():
    from app.assistant_controller import missing_outcomes

    outcomes = [{"kind": "project", "count": 1}, {"kind": "local_changes", "count": 1}]
    empty = {"tool": "project.create", "status": "succeeded", "produced_types": ["json"]}
    assert missing_outcomes([empty], outcomes) == [{"kind": "local_changes", "count": 1, "remaining": 1}]
    built = {"tool": "project.create_code", "status": "succeeded", "produced_types": ["git_diff", "archive"]}
    assert missing_outcomes([built], outcomes) == []
