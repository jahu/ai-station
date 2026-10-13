import base64
import io
from uuid import uuid4

import pytest
from ai_station_runner.app import app
from ai_station_runner.vision_messages import VisionCompletion
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError


def payload():
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(output, "PNG")
    url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return {
        "model": str(uuid4()),
        "temperature": 0.1,
        "max_tokens": 32,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe"},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
    }


def test_valid_inline_pixels_are_forwarded_without_file_or_url_access():
    data = payload()
    assert VisionCompletion.model_validate(data).model_dump() == data


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/photo.png",
        "http://127.0.0.1:8765/secret",
        "file:///etc/passwd",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/png;base64,invalid",
        "data:image/png;base64,iVBORw0KGgo=",
    ],
)
def test_remote_paths_unsupported_and_invalid_images_are_rejected(url):
    data = payload()
    data["messages"][0]["content"][1]["image_url"]["url"] = url
    with pytest.raises(ValidationError):
        VisionCompletion.model_validate(data)


def test_too_many_images_are_rejected_before_image_decoding(monkeypatch):
    from ai_station_runner import vision_messages

    data = payload()
    data["messages"][0]["content"] = [data["messages"][0]["content"][1]] * 5
    calls = []
    monkeypatch.setattr(vision_messages.base64, "b64decode", lambda *args, **kwargs: calls.append(True))
    with pytest.raises(ValidationError):
        VisionCompletion.model_validate(data)
    assert calls == []


def test_image_error_responses_never_echo_the_payload():
    data = payload()
    secret = "PRIVATE_IMAGE_BYTES"
    data["messages"][0]["content"][1]["image_url"]["url"] = "data:image/png;base64," + secret
    with TestClient(app) as client:
        response = client.post("/v1/llama/" + data["model"] + "/chat/completions", json=data)
    assert response.status_code == 422
    assert secret not in response.text
    assert "base64" not in response.text


def test_images_cannot_be_injected_as_system_messages():
    data = payload()
    data["messages"][0]["role"] = "system"
    with pytest.raises(ValidationError):
        VisionCompletion.model_validate(data)


def test_images_require_a_projector_before_any_upstream_request(monkeypatch):
    from ai_station_runner import llama_runtime

    data = payload()
    monkeypatch.setattr(llama_runtime, "manifest", lambda _: {"desired": "running", "projector": None})
    with TestClient(app) as client:
        response = client.post("/v1/llama/" + data["model"] + "/chat/completions", json=data)
    assert response.status_code == 409
    assert "vision projector" in response.text
