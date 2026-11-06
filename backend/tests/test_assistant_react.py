import asyncio

import pytest
from app.assistant_react import forbidden, take_action


def test_framework_selects_typed_action_without_executing_a_tool():
    calls = []

    async def infer(messages):
        calls.append(messages)
        return 'Thought: Put the supplied object in the requested location.\nAction: image_recompose\nAction Input: {"instruction":"A blue cabinet in a garden","images":["input:image:1"]}'

    value = asyncio.run(
        take_action(
            {
                "instruction": "Put this cabinet in a garden",
                "tools": {"image.recompose": {}},
                "observations": [],
            },
            infer,
        )
    )
    assert value["tool"] == "image.recompose" and value["arguments"]["images"] == ["input:image:1"]
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="only the durable"):
        asyncio.run(forbidden())


def test_framework_uses_real_observation_when_selecting_the_next_action():
    async def infer(messages):
        content = "\n".join(row["content"] for row in messages)
        assert '"status": "succeeded"' in content and '"index": 1' in content
        assert "step:1:image:1" in content
        return 'Thought: Prepare the requested recurring workflow from its result.\nAction: agent_create\nAction Input: {"instruction":"A new cabinet view every 15 minutes"}'

    context = {
        "instruction": "Modify this cabinet, then prepare an agent using the result every 15 minutes",
        "tools": {"agent.create": {}},
        "inputs_and_results": [{"alias": "step:1:image:1", "type": "image"}],
        "observations": [
            {
                "index": 1,
                "tool": "image.recompose",
                "arguments": {"instruction": "A blue cabinet", "images": ["input:image:1"]},
                "status": "succeeded",
                "produced_types": ["image"],
            }
        ],
    }
    assert asyncio.run(take_action(context, infer))["tool"] == "agent.create"


def test_framework_does_not_claim_unobserved_work_completed():
    async def infer(messages):
        return "Thought: Finished.\nAnswer: Your image is ready."

    with pytest.raises(ValueError, match="unfinished"):
        asyncio.run(
            take_action(
                {
                    "instruction": "Modify this cabinet",
                    "tools": {"image.recompose": {}},
                    "missing_outcomes": [{"kind": "image", "remaining": 1}],
                    "observations": [],
                },
                infer,
            )
        )


def test_framework_clarification_does_not_dispatch_a_workload():
    async def infer(messages):
        return 'Thought: Ask which background is desired.\nAction: ask_user\nAction Input: {"question":"Would you prefer a garden or a studio?"}'

    value = asyncio.run(
        take_action({"instruction": "Change this image", "tools": {}, "observations": []}, infer)
    )
    assert value == {
        "kind": "clarify",
        "reason": "Clarify the requested result",
        "response": "Would you prefer a garden or a studio?",
    }


def test_framework_bounds_observation_excerpts_without_changing_canonical_results():
    from app.assistant_react import bounded_context

    source = {
        "instruction": "Keep the actual original request",
        "observations": [
            {
                "index": 1,
                "tool": "web.read",
                "status": "succeeded",
                "arguments": {"sources": ["web:1"]},
                "tool_data_excerpt": "x" * 20000,
                "responses": ["y" * 10000],
            }
        ],
    }
    bounded = bounded_context(source)
    assert len(bounded["observations"][0]["tool_data_excerpt"]) == 1200
    assert bounded["observations"][0]["context_excerpt_truncated"]
    assert bounded["instruction"] == source["instruction"]
    assert bounded["observations"][0]["arguments"] == {"sources": ["web:1"]}
    assert len(source["observations"][0]["tool_data_excerpt"]) == 20000
