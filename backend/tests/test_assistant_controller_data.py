"""Actual data/Python contracts feed a disabled factory draft in the same turn."""

import json

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


def test_data_then_source_bound_agent_chain_preserves_verified_inputs_without_model_generated_ids(
    data_environment, monkeypatch
):
    original = LocalChatProvider.stream

    async def stream(self, **params):
        if params["messages"][0]["content"].startswith("Infer the user's requested outcomes"):
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
        if params["messages"][0]["content"].startswith("You operate AI Station"):
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
