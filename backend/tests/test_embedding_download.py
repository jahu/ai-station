"""Pinned model transfers do not accept arbitrary targets, late Stop or corrupt bytes."""

import hashlib

import httpx
import pytest
from app import embedding_download as downloads
from app import embedding_models as models
from app.config import get_settings
from app.db import session_factory
from app.embedding_process import EmbeddingStopped
from app.models import Run
from app.providers import ProviderError
from app.runs import create_run, create_task, request_cancel


@pytest.fixture
def transfer(monkeypatch):
    data = b"controlled synthetic model bytes"
    spec = {"remote": "model_quantized.onnx", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(models, "FILES", {"model_quantized.onnx": spec})
    monkeypatch.setattr(downloads, "FILES", {"model_quantized.onnx": spec})

    async def addresses(_):
        return ["93.184.216.34"]

    monkeypatch.setattr(downloads, "public_addresses", addresses)
    original = httpx.AsyncClient
    state = {"body": data, "redirect": None, "status": 200, "requests": [], "client_class": original}

    def handler(request):
        state["requests"].append(request)
        if state["redirect"]:
            return httpx.Response(302, headers={"Location": state["redirect"]})
        return httpx.Response(state["status"], content=state["body"])

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    return state


def running(session):
    task = create_task(session, title="Controlled download", prompt="", capability="memory.embed.prepare")
    run = create_run(
        session, task, run_type="memory", capability="memory.embed.prepare", executor_type="memory_embed"
    )
    run.status = "running"
    session.commit()
    return run


@pytest.mark.parametrize("valid", [True, False])
async def test_only_exact_verified_bytes_are_adopted_and_parts_are_cleaned(transfer, valid):
    if not valid:
        transfer["body"] = b"x" * len(transfer["body"])
    root = get_settings().data_dir
    with session_factory()() as session:
        run = running(session)
        if valid:
            await downloads.download_file(session, run, root, "model_quantized.onnx")
            assert models.model_file(root, "model_quantized.onnx").read_bytes() == transfer["body"]
        else:
            with pytest.raises(ValueError, match="verification"):
                await downloads.download_file(session, run, root, "model_quantized.onnx")
            assert not models.model_file(root, "model_quantized.onnx").exists()
    assert not list(models.directory(root).glob("*.part"))
    assert transfer["requests"][0].url.host == "93.184.216.34"
    assert transfer["requests"][0].headers["host"] == "huggingface.co"


async def test_redirect_to_local_service_is_rejected_before_a_second_request(transfer):
    transfer["redirect"] = "http://127.0.0.1:8765/api/runs"
    with session_factory()() as session:
        with pytest.raises(ValueError, match="public HTTPS"):
            await downloads.download_file(
                session, running(session), get_settings().data_dir, "model_quantized.onnx"
            )
    assert len(transfer["requests"]) == 1


async def test_download_error_does_not_expose_signed_url_or_tokens(transfer):
    transfer["status"] = 403
    with session_factory()() as session:
        with pytest.raises(ProviderError) as error:
            await downloads.download_file(
                session, running(session), get_settings().data_dir, "model_quantized.onnx"
            )
    assert "huggingface" not in str(error.value) and "http" not in str(error.value)


async def test_stop_during_download_never_adopts_complete_bytes(transfer, monkeypatch):
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            with session_factory()() as other:
                request_cancel(other, other.get(Run, rid))
                other.commit()
            yield transfer["body"]

    original = transfer["client_class"]
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks()))
        ),
    )
    with session_factory()() as session:
        run = running(session)
        rid = run.id
        with pytest.raises(EmbeddingStopped):
            await downloads.download_file(session, run, get_settings().data_dir, "model_quantized.onnx")
    assert not models.model_file(get_settings().data_dir, "model_quantized.onnx").exists()
    assert not list(models.directory(get_settings().data_dir).glob("*.part"))


@pytest.mark.parametrize("phase", ["dns", "headers"])
async def test_stop_also_interrupts_waiting_for_dns_or_response_headers(transfer, monkeypatch, phase):
    import asyncio

    async def stall(*_):
        with session_factory()() as other:
            request_cancel(other, other.get(Run, rid))
            other.commit()
        await asyncio.sleep(120)

    if phase == "dns":
        monkeypatch.setattr(downloads, "public_addresses", stall)
    else:
        original = transfer["client_class"]
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(stall)),
        )
    with session_factory()() as session:
        run = running(session)
        rid = run.id
        async with asyncio.timeout(3):
            with pytest.raises(EmbeddingStopped):
                await downloads.download_file(session, run, get_settings().data_dir, "model_quantized.onnx")
    assert not models.model_file(get_settings().data_dir, "model_quantized.onnx").exists()
    assert not list(models.directory(get_settings().data_dir).glob("*.part"))


@pytest.mark.parametrize("extra", [-1, 1])
async def test_short_or_oversized_files_are_never_adopted(transfer, extra):
    transfer["body"] = transfer["body"][:-1] if extra < 0 else transfer["body"] + b"x"
    with session_factory()() as session:
        with pytest.raises(ValueError):
            await downloads.download_file(
                session, running(session), get_settings().data_dir, "model_quantized.onnx"
            )
    assert not models.model_file(get_settings().data_dir, "model_quantized.onnx").exists()
    assert not list(models.directory(get_settings().data_dir).glob("*.part"))
