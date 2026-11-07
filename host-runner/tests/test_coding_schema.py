import asyncio
import json

import httpx
import pytest
from ai_station_runner.coding_files import parse_proposal
from ai_station_runner.local_model import CodingCompletion, Completion, forward_completion
from pydantic import ValidationError
from starlette.requests import Request

BODY = {
    "model": "fixture",
    "messages": [{"role": "user", "content": "Change the selected source only"}],
    "temperature": 0.1,
    "max_tokens": 16384,
    "stream": True,
    "proposal_paths": ["src/index.html", "src/style.css"],
}


@pytest.mark.parametrize("paths", [[], ["a"] * 2, ["a"] * 11, ["x" * 301]])
def test_proposal_path_contract_is_bounded_and_not_accepted_by_chat(paths):
    with pytest.raises(ValidationError):
        CodingCompletion.model_validate({**BODY, "proposal_paths": paths})
    with pytest.raises(ValidationError):
        Completion.model_validate({**BODY, "max_tokens": 100})


def test_owned_proposal_schema_is_compiled_for_the_selected_paths_only():
    captured = []

    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: [DONE]\n\n")

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        response = await forward_completion(
            CodingCompletion.model_validate(BODY), Request({"type": "http"}), "http://llama/v1", client, {}
        )
        async for _ in response.body_iterator:
            pass
        assert client.is_closed

    asyncio.run(exercise())
    actual = captured[0]
    assert "proposal_paths" not in actual and "response_fields" not in actual
    assert actual["reasoning_effort"] == "none" and actual["max_tokens"] == 16384
    schema = actual["response_format"]["schema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["summary", "files"]
    variants = schema["properties"]["files"]["items"]["oneOf"]
    assert [v["required"] for v in variants] == [
        ["path", "content"],
        ["path", "replacements"],
        ["path", "delete"],
    ]
    assert all(
        v["additionalProperties"] is False and v["properties"]["path"]["enum"] == BODY["proposal_paths"]
        for v in variants
    )
    # The schema is an output constraint, never permission to bypass final
    # checked application (including duplicate/unselected paths and stale data).
    with pytest.raises(ValueError, match="unselected"):
        parse_proposal(
            json.dumps({"summary": "No", "files": [{"path": "other.py", "content": "text"}]}),
            [{"path": "src/index.html", "content": None}],
            local_context=True,
        )


def test_ordinary_coding_omits_the_optional_schema_and_rejects_conflicting_output_bounds():
    body = {k: v for k, v in BODY.items() if k != "proposal_paths"}
    assert "proposal_paths" not in CodingCompletion.model_validate(body).model_dump()
    with pytest.raises(ValidationError):
        CodingCompletion.model_validate({**BODY, "response_fields": {"prompt": 100}})


@pytest.mark.parametrize("tools", [[], ["finish"] * 2, ["shell"]])
def test_exploration_schema_cannot_advertise_arbitrary_or_duplicate_tools(tools):
    body = {k: v for k, v in BODY.items() if k != "proposal_paths"}
    with pytest.raises(ValidationError):
        CodingCompletion.model_validate({**body, "exploration_tools": tools})


def test_exploration_compiles_only_the_declared_operations_and_bounded_selection():
    captured = []
    body = {k: v for k, v in BODY.items() if k != "proposal_paths"}
    body.update(max_tokens=2048, exploration_tools=["list_files", "read_file", "finish"])

    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: [DONE]\n\n")

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        response = await forward_completion(
            CodingCompletion.model_validate(body), Request({"type": "http"}), "http://llama/v1", client, {}
        )
        async for _ in response.body_iterator:
            pass

    asyncio.run(exercise())
    actual = captured[0]
    assert "exploration_tools" not in actual and actual["max_tokens"] == 2048
    variants = actual["response_format"]["schema"]["oneOf"]
    assert {v["properties"]["tool"]["const"] for v in variants} == set(body["exploration_tools"])
    assert all(v["additionalProperties"] is False for v in variants)
    finish = next(v for v in variants if v["properties"]["tool"]["const"] == "finish")
    assert finish["properties"]["files"]["minItems"] == 1
    assert finish["properties"]["files"]["maxItems"] == 10
    with pytest.raises(ValidationError):
        CodingCompletion.model_validate({**BODY, "exploration_tools": ["finish"]})
