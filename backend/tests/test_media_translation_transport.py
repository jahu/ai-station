import asyncio
import json

import httpx
import pytest
from app.config import clear_settings_cache
from app.local_provider import LocalChatProvider, local_endpoint
from app.providers import ProviderError


@pytest.mark.parametrize("finish_reason", ["stop", "length", "content_filter"])
def test_translation_requires_a_complete_model_response_without_new_runner_fields(monkeypatch, finish_reason):
    monkeypatch.setenv("AI_STATION_LLM_TRANSPORT", "direct")
    clear_settings_cache()
    client = httpx.AsyncClient
    requests = []
    content = '{"prompt":"A red bicycle"}'
    records = "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"
    records += (
        "data: "
        + json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason}]})
        + "\n\ndata: [DONE]\n\n"
    )

    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=records)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(reply))
    )

    async def consume():
        return "".join(
            [
                token
                async for token in LocalChatProvider().stream(
                    endpoint=local_endpoint(),
                    messages=[{"role": "user", "content": "rower"}],
                    model="local-translator",
                    temperature=0,
                    max_tokens=128,
                    json_output=True,
                    require_complete=True,
                )
            ]
        )

    if finish_reason == "stop":
        assert asyncio.run(consume()) == content
    else:
        with pytest.raises(ProviderError, match="did not complete"):
            asyncio.run(consume())
    assert "tools" not in requests[0] and "require_complete" not in requests[0]
