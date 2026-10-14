import json
from types import SimpleNamespace

import httpx
import pytest
from ai_station_runner import local_coding_job


@pytest.mark.parametrize("managed", [False, True])
def test_coding_requests_confirmed_json_for_managed_and_configured_local_models(monkeypatch, managed):
    recorded = []
    instance = "12345678-1234-4234-8234-123456789abc"
    body = SimpleNamespace(
        model="llamacpp:model" if managed else "local",
        endpoint="llamacpp:" + instance if managed else "http://localhost:11434/v1",
    )

    def reply(request):
        recorded.append(json.loads(request.content))
        event = {"choices": [{"delta": {"content": '{"summary":"OK","files":[]}'}, "finish_reason": "stop"}]}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
        )

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **_: httpx.MockTransport(reply))
    text, _ = local_coding_job.collect_completion(body, "Return one JSON object")
    assert json.loads(text)["summary"] == "OK"
    assert recorded[0]["json_output"] is True
    assert recorded[0]["stream"] is True
