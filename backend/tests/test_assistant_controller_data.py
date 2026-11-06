"""Actual data/Python contracts feed a disabled factory draft in the same turn."""

import json

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import drain, tool
from test_conversation_data import inspected
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize("react_protocol", [False, True])
def test_data_then_source_bound_agent_chain_preserves_verified_inputs_without_model_generated_ids(
    data_environment, monkeypatch, react_protocol
):
    if react_protocol:
        monkeypatch.setattr("app.assistant_controller.PROTOCOL", "llamaindex-react-v1")
    original = LocalChatProvider.stream

    async def stream(self, **params):
        if params["messages"][0]["content"].startswith("Infer the user's requested outcomes"):
            if react_protocol:
                yield json.dumps(
                    {
                        "reason": "Analyze and prepare an agent",
                        "immediate": [{"kind": "text", "description": "The verified total"}],
                        "automations": [
                            {
                                "goal": "Repeat the verified analysis",
                                "schedule": {"trigger": "interval", "interval_seconds": 300},
                            }
                        ],
                    }
                )
                return
            yield json.dumps(
                {
                    "reason": "Analyze and prepare an agent",
                    "outcomes": [
                        {"kind": "text", "count": 1, "description": "The verified total"},
                        {
                            "kind": "agent_draft",
                            "count": 1,
                            "description": "A disabled agent repeating that analysis",
                        },
                    ],
                }
            )
            return
        if react_protocol and "Action Input" in params["messages"][0]["content"]:
            from test_assistant_react_workflow import action

            state = next(
                json.loads(message["content"].split("\n", 1)[1])
                for message in params["messages"]
                if message["content"].startswith("CURRENT REQUEST AND AVAILABLE STATE:")
            )
            if not state["analysis_results"]:
                yield action("data_analyze", instruction="Calculate the total in the selected file.")
            elif any(item["kind"] == "agent_draft" for item in state["missing_outcomes"]):
                yield action(
                    "agent_create",
                    instruction="Repeat the verified analysis every five minutes",
                    analysis=state["analysis_results"][0]["alias"],
                    interval_seconds=300,
                )
            else:
                yield action("chat_reply", instruction="Explain the total and the disabled recurring draft")
        elif params["messages"][0]["content"].startswith("You operate AI Station"):
            context = json.loads(params["messages"][1]["content"])
            if not context["observations"]:
                value = {
                    **tool("data.analyze", instruction="Calculate the total in the selected file."),
                    "outcomes": [
                        {"kind": "text", "count": 1, "description": "The verified total"},
                        {
                            "kind": "agent_draft",
                            "count": 1,
                            "description": "A disabled agent repeating that analysis",
                        },
                    ],
                }
            elif len(context["observations"]) == 1:
                assert context["analysis_results"]
                value = tool(
                    "agent.create",
                    instruction="Repeat the verified analysis every five minutes",
                    analysis=context["analysis_results"][0]["alias"],
                )
            else:
                value = tool("chat.reply", instruction="Explain the total and the disabled recurring draft")
            value.pop("outcomes", None)  # Intent is independently frozen before tool selection.
            yield json.dumps(value)
        elif "proposal_schema" in json.dumps(params["messages"]):
            yield json.dumps({"name": "Totals watcher", "trigger": "interval", "interval_seconds": 300})
        else:
            async for value in original(self, **params):
                yield value

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        aid = inspected(api)
        response = api.post(
            "/api/chat/turns",
            json={
                "client_request_id": "6b048313-1e90-4a22-85bd-cb9d7a29468f",
                "selection": {"execution_mode": "assistant", "model": data_environment["model"]},
                "content": "Calculate the total in this file, then prepare an agent to repeat the analysis every five minutes",
                "data": {"input_artifact_ids": [aid], "model": data_environment["model"]},
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        with session_factory()() as db:
            root = db.get(Run, response.json()["run"]["id"])
            assert root.status == "succeeded", root.error_message
            assert [step["tool"] for step in root.metadata_json["controller_steps"]] == [
                "data.analyze",
                "agent.create",
                "chat.reply",
            ]
            agent = db.scalar(select(Agent))
            assert agent and not agent.enabled and agent.tools == ["python_data"]
            assert agent.data["input_artifact_ids"] == [aid]
            assert agent.goal == "Calculate the total in the selected file."
            assert data_environment["calls"] == 1


# Preserve regression coverage for queued/history JSON-controller Runs.
pytestmark = pytest.mark.usefixtures("legacy_controller_protocol")
