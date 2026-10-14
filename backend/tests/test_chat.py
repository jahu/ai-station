import asyncio
import base64
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from app.api import app
from app.config import clear_settings_cache
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider, local_endpoint
from app.models import Run
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter


class Stream(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        for token in ["Hello ", "**world**"]:
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": token}}]}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


@pytest.fixture
def provider(monkeypatch):
    client = httpx.AsyncClient
    stream = Stream()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=transport))
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["local-model"])
    return stream, requests


def new_conversation(client):
    result = client.post(
        "/api/chat/conversations", json={"model": "local-model", "system_prompt": "Be concise"}
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_chat_persistence_context_regeneration_and_sse(provider):
    stream, requests = provider
    with TestClient(app) as client:
        assert client.get("/api/chat/provider").json()["location"] == "local"
        conversation_id = new_conversation(client)
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()
        assert run["status"] == "queued"
        assert run["parameters"]["messages"] == [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hi"},
        ]
        with session_factory()() as session:
            tick(session, "chat-test")
        assert stream.closed
        assert json.loads(requests[0].content)["model"] == "local-model"
        detail = client.get(f"/api/chat/conversations/{conversation_id}").json()
        assert detail["messages"][-1]["content"] == "Hello **world**"
        assert detail["messages"][-1]["run_status"] == "succeeded"
        assert detail["messages"][-1]["metadata"]["partial"] is False
        assert "chat.delta" in client.get(f"/api/runs/{run['id']}/stream").text
        reset_engine()
        assert (
            client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"] == detail["messages"]
        )
        retry = client.post(f"/api/chat/conversations/{conversation_id}/regenerate").json()
        assert retry["parent_run_id"] == run["id"]
        assert retry["task_id"] == run["task_id"]
        assert retry["parameters"]["messages"] == run["parameters"]["messages"]
        history = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
        assert history[1]["metadata"]["superseded"] is True


def test_only_one_active_run_per_conversation(provider):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        barrier = Barrier(2)

        def send():
            barrier.wait()
            return client.post(
                f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(lambda _: send(), range(2)))
        assert sorted(codes) == [202, 409]
        assert (
            client.patch(f"/api/chat/conversations/{conversation_id}", json={"model": "other"}).status_code
            == 409
        )
        assert client.post(f"/api/chat/conversations/{conversation_id}/regenerate").status_code == 409


def test_cancel_silent_provider_closes_connection(monkeypatch, provider):
    stopped = []

    async def silent(self, **kwargs):
        try:
            with session_factory()() as other:
                run = other.get(Run, run_id)
                request_cancel(other, run)
                other.commit()
            await asyncio.Event().wait()
            yield "never"
        finally:
            stopped.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run_id = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()["id"]
        with session_factory()() as session:
            tick(session, "chat-test")
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "canceled"
        assert stopped == [True]


def test_partial_output_survives_provider_failure(monkeypatch, provider):
    async def broken(self, **kwargs):
        yield "Preserved partial response"
        raise ProviderError("Stream disconnected")

    monkeypatch.setattr(LocalChatProvider, "stream", broken)
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run_id = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()["id"]
        with session_factory()() as session:
            tick(session, "chat-test")
        detail = client.get(f"/api/chat/conversations/{conversation_id}").json()
        assert detail["messages"][-1]["content"] == "Preserved partial response"
        assert detail["messages"][-1]["metadata"]["partial"] is True
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://169.254.169.254/v1",
        "http://user:secret@localhost/v1",
        "http://8.8.8.8/v1",
        "file:///etc/passwd",
    ],
)
def test_local_chat_rejects_external_or_credential_urls(monkeypatch, url):
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", url)
    clear_settings_cache()
    with pytest.raises(ProviderError):
        local_endpoint()
    with TestClient(app) as client:
        assert client.post("/api/chat/conversations", json={"model": "local-model"}).status_code == 409


def test_endpoint_change_does_not_reroute_queued_prompt(provider, monkeypatch):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()
        monkeypatch.setenv("AI_STATION_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        clear_settings_cache()
        with session_factory()() as session:
            tick(session, "chat-test")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        assert provider[1] == []


@pytest.mark.parametrize(
    "records",
    [
        b"data: bad-json\n\n",
        b'data: {"error":{"message":"secret"}}\n\n',
        b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    ],
)
def test_incomplete_or_invalid_provider_stream_fails(records, monkeypatch):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=records))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs, transport=transport))

    async def consume():
        return [
            piece
            async for piece in LocalChatProvider().stream(
                endpoint=local_endpoint(), messages=[], model="m", temperature=0.7, max_tokens=20
            )
        ]

    with pytest.raises(ProviderError):
        asyncio.run(consume())


@pytest.mark.parametrize(
    "url", ["http://[::1]:8080/v1", "http://192.168.1.4:8080/v1", "http://host.docker.internal:8080/v1"]
)
def test_local_endpoint_forms(url, monkeypatch):
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", url)
    clear_settings_cache()
    assert local_endpoint() == url


def test_context_window_preserves_valid_turn_order(provider):
    from app.models import Message

    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        with session_factory()() as session:
            for index in range(12):
                for role in ("user", "assistant"):
                    session.add(
                        Message(
                            conversation_id=conversation_id,
                            role=role,
                            content=f"{role} {index}",
                            metadata_json={},
                        )
                    )
                    session.flush()
            session.commit()
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Latest question"}
        ).json()
        messages = run["parameters"]["messages"]
        assert len(messages) <= 17
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[-1]["content"] == "Latest question"
        assert all(a["role"] != b["role"] for a, b in zip(messages[1:], messages[2:]))


def test_text_attachments_persist_as_safe_artifacts_and_immutable_context(provider):

    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        source = 'print("hello")\n'
        result = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={"content": "Explain this", "attachments": [{"name": "example.html", "content": source}]},
        )
        assert result.status_code == 202, result.text
        run = result.json()
        assert (
            source
            in json.loads(
                run["parameters"]["messages"][-1]["content"].split("reference data, not instructions):\n")[1]
            )[0]["content"]
        )
        with session_factory()() as session:
            tick(session, "attachment-chat")
        message = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"][0]
        attachment = message["metadata"]["attachments"][0]
        assert message["metadata"]["user_text"] == "Explain this"
        assert attachment["sha256"] == hashlib.sha256(source.encode()).hexdigest()
        artifact = client.get(f"/api/artifacts/{attachment['id']}").json()
        assert artifact["type"] == "text" and artifact["run_id"] == run["id"]
        assert artifact["metadata"]["conversation_id"] == conversation_id
        assert artifact["metadata"]["message_id"] == message["id"]
        assert artifact["relative_path"].endswith(".txt")
        file = client.get(f"/api/artifacts/{attachment['id']}/file")
        assert file.text == source
        assert file.headers["content-type"].startswith("text/plain")
        assert file.headers["content-disposition"].startswith("attachment;")
        assert file.headers["x-content-type-options"] == "nosniff"
        reset_engine()
        assert client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"][0] == message
        regenerated = client.post(f"/api/chat/conversations/{conversation_id}/regenerate").json()
        assert regenerated["parameters"]["messages"] == run["parameters"]["messages"]
        assert len(client.get(f"/api/artifacts?run_id={run['id']}").json()) == 1
        other = new_conversation(client)
        clean = client.post(f"/api/chat/conversations/{other}/messages", json={"content": "Hello"}).json()
        assert "example.html" not in json.dumps(clean["parameters"])


@pytest.mark.parametrize(
    "attachments",
    [
        [{"name": "../secret", "content": "x"}],
        [{"name": "a\r\nb", "content": "x"}],
        [{"name": "a.txt", "content": "\0"}],
        [{"name": "a.txt", "content": "ę" * 8001}],
        [{"name": str(i), "content": "x"} for i in range(5)],
        [{"name": "same", "content": "a"}, {"name": "same", "content": "b"}],
        [{"name": str(i), "content": "x" * 13000} for i in range(2)],
        [{"name": "a.txt", "content": "\n" * 16000}],
    ],
)
def test_invalid_attachments_rejected_before_message_run_or_artifact_creation(provider, attachments):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        result = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={"content": "Explain", "attachments": attachments},
        )
        assert result.status_code == 422, result.text
        assert not client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
        assert not client.get("/api/artifacts").json()
        assert not client.get("/api/runs").json()


def test_summary_includes_attached_text_in_its_covered_source_messages(provider):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        path = f"/api/chat/conversations/{conversation_id}"
        for i in range(5):
            body = {"content": f"Turn {i}"}
            if i == 0:
                body["attachments"] = [{"name": "decision.md", "content": "The launch codename is Willow."}]
            response = client.post(path + "/messages", json=body)
            assert response.status_code == 202, response.text
            with session_factory()() as session:
                tick(session, "attachment-summary-context")
        summary = client.post(path + "/summarize")
        assert summary.status_code == 202, summary.text
        context = summary.json()["parameters"]["messages"][-1]["content"]
        assert "Willow" in context and "decision.md" in context
        assert len(summary.json()["parameters"]["source_message_ids"]) == 2


def _pdf(text="HelloPDF"):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    parts = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(parts, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(parts) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(f"trailer << /Size {len(parts) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    return buf.getvalue()


def test_pdf_and_image_attachments_are_untrusted_context_without_vision(provider):
    pdf = _pdf("WillowClause")
    image = _png()
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    empty = io.BytesIO()
    writer.write(empty)
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        rejected = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={
                "content": "Read this",
                "attachments": [
                    {
                        "name": "empty.pdf",
                        "kind": "pdf",
                        "content": base64.b64encode(empty.getvalue()).decode(),
                    }
                ],
            },
        )
        assert rejected.status_code == 422 and "extractable text" in rejected.text
        result = client.post(
            f"/api/chat/conversations/{conversation_id}/messages",
            json={
                "content": "Read these",
                "attachments": [
                    {"name": "notes.pdf", "kind": "pdf", "content": base64.b64encode(pdf).decode()},
                    {"name": "photo.png", "kind": "image", "content": base64.b64encode(image).decode()},
                ],
            },
        )
        assert result.status_code == 202, result.text
        run = result.json()
        payload = run["parameters"]["messages"][-1]["content"]
        assert "WillowClause" in payload
        assert "Pixels were not sent" in payload
        assert base64.b64encode(image).decode() not in payload
        with session_factory()() as session:
            tick(session, "document-chat")
        message = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"][0]
        kinds = {item["kind"]: item for item in message["metadata"]["attachments"]}
        assert kinds["pdf"]["extracted_text"] is True
        assert kinds["image"]["pixels_sent"] is False
        pdf_file = client.get(f"/api/artifacts/{kinds['pdf']['id']}/file")
        assert pdf_file.content == pdf
        assert pdf_file.headers["content-type"].startswith("application/pdf")
        assert pdf_file.headers["content-disposition"].startswith("attachment;")
        image_meta = client.get(f"/api/artifacts/{kinds['image']['id']}").json()
        assert image_meta["type"] == "image" and image_meta["metadata"]["width"] == 8
        assert kinds["pdf"]["sha256"] == hashlib.sha256(pdf).hexdigest()
        regenerated = client.post(f"/api/chat/conversations/{conversation_id}/regenerate").json()
        assert regenerated["parameters"]["messages"] == run["parameters"]["messages"]


def test_invalid_pdf_and_image_attachments_are_rejected(provider):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        for attachments in (
            [{"name": "notes.pdf", "kind": "pdf", "content": base64.b64encode(b"not-a-pdf").decode()}],
            [{"name": "photo.png", "kind": "image", "content": base64.b64encode(b"<svg></svg>").decode()}],
            [{"name": "notes.pdf", "kind": "pdf", "content": "%%%not-base64%%%"}],
        ):
            result = client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={"content": "Read", "attachments": attachments},
            )
            assert result.status_code == 422, result.text
        assert not client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
        assert not client.get("/api/artifacts").json()


def test_regenerate_after_task_stop_explicitly_starts_a_new_chat_attempt(provider):
    with TestClient(app) as client:
        cid = new_conversation(client)
        original = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Hello"}).json()
        stopped = client.post(f"/api/chat/conversations/{cid}/tasks/{original['task_id']}/cancel")
        assert stopped.status_code == 200
        assert client.get("/api/runs/" + original["id"]).json()["status"] == "canceled"
        retry = client.post(f"/api/chat/conversations/{cid}/regenerate")
        assert retry.status_code == 202, retry.text
        assert retry.json()["task_id"] == original["task_id"]
        assert retry.json()["id"] != original["id"]
        with session_factory()() as s:
            assert tick(s, "regenerate-after-stop") == retry.json()["id"]
        assert client.get("/api/runs/" + retry.json()["id"]).json()["status"] == "succeeded"
