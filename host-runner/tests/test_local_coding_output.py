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


def streamed_completion(monkeypatch, events, max_tokens=8192):
    body = SimpleNamespace(model="local", endpoint="http://localhost:11434/v1")

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for event in events:
                yield b"data: " + json.dumps(event).encode() + b"\n\n"
            yield b"data: [DONE]\n\n"

    def reply(request):
        assert json.loads(request.content)["max_tokens"] == max_tokens
        assert request.url.path.endswith("/coding/completions" if max_tokens > 8192 else "/chat/completions")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **_: httpx.MockTransport(reply))
    return local_coding_job.collect_completion(body, "Implement a working deliverable", max_tokens=max_tokens)


@pytest.mark.parametrize("max_tokens", [8192, 16384])
def test_sse_metadata_does_not_consume_the_actual_coding_content_budget(monkeypatch, max_tokens):
    # Real token streams repeat request/model/timing metadata in every frame.
    # More than 2 MiB on the wire can still contain a small, valid proposal.
    text = json.dumps({"summary": "Ready " + "x" * 550, "files": []})
    events = [{"metadata": "m" * 4096, "choices": [{"delta": {"content": char}}]} for char in text]
    events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    assert sum(len(json.dumps(event).encode()) for event in events) > 2 * 1024 * 1024
    actual, _ = streamed_completion(monkeypatch, events, max_tokens=max_tokens)
    assert actual == text and json.loads(actual)["files"] == []


@pytest.mark.parametrize("bound", ["content", "event size", "stream transport"])
def test_separate_stream_limits_remain_bounded(monkeypatch, bound):
    if bound == "content":
        # UTF-8 byte accounting, not character counting; each event is small.
        events = [{"choices": [{"delta": {"content": "ą" * 4096}}]}] * 257
    elif bound == "event size":
        events = [{"metadata": "x" * local_coding_job.MAX_CONTENT_BYTES, "choices": []}]
    else:
        events = [{"metadata": "x" * 65536, "choices": []}] * 257
    with pytest.raises(ValueError, match=bound + " limit"):
        streamed_completion(monkeypatch, events)
