"""Typed access to one configured local inference endpoint over the private UDS."""

import asyncio
import ipaddress
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

import anyio
import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.config import get_settings

router = APIRouter(prefix="/v1/llm")
ExpectedEndpoint = Annotated[str, Header(alias="X-AI-Station-Endpoint", max_length=1000)]


def endpoint(expected):
    raw = get_settings().llm_base_url.rstrip("/")
    try:
        url = urlsplit(raw)
        _ = url.port
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Invalid endpoint")
        if url.hostname not in {"localhost", "host.docker.internal"}:
            address = ipaddress.ip_address(url.hostname)
            private = [
                ipaddress.ip_network(net)
                for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
            ]
            if not address.is_loopback and not any(address in network for network in private):
                raise ValueError("External endpoint")
    except ValueError as exc:
        raise HTTPException(
            409, "Configure a local HTTP(S) model endpoint without credentials in its URL"
        ) from exc
    if expected != raw:
        raise HTTPException(409, "Local model endpoint differs between control plane and Host Runner")
    return raw


def headers():
    key = get_settings().llm_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


def upstream_client():
    return httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10), trust_env=False, follow_redirects=False)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=100000)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(ge=1, le=8192)
    stream: Literal[True]

    @model_validator(mode="after")
    def bound_context(self):
        if sum(len(message.content) for message in self.messages) > 128000:
            raise ValueError("Model context exceeds the bridge limit")
        return self


@router.get("/models")
async def models(expected: ExpectedEndpoint):
    url = endpoint(expected)
    try:
        async with upstream_client() as client:
            async with client.stream("GET", url + "/models", headers=headers(), timeout=5) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise ValueError("Too large")
            payload = json.loads(data)
            names = sorted(
                {
                    item["id"]
                    for item in payload["data"]
                    if isinstance(item.get("id"), str) and len(item["id"]) <= 200
                }
            )
            return {"data": [{"id": name} for name in names[:1000]]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Local model discovery failed") from exc


async def send_until_disconnect(client, upstream, incoming):
    """Close a queued inference request even before the provider sends headers."""
    pending = asyncio.create_task(client.send(upstream, stream=True))
    returned = False
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=0.1)
            if done:
                response = pending.result()
                returned = True
                return response
            if await incoming.is_disconnected():
                raise HTTPException(499, "Model client disconnected")
    finally:
        if not returned:
            pending.cancel()
            with anyio.CancelScope(shield=True):
                result = (await asyncio.gather(pending, return_exceptions=True))[0]
                if isinstance(result, httpx.Response):
                    await result.aclose()


@router.post("/chat/completions")
async def completion(body: Completion, expected: ExpectedEndpoint, incoming: Request):
    url = endpoint(expected)
    client = upstream_client()
    return await forward_completion(body, incoming, url, client, headers())


async def forward_completion(body, incoming, url, client, request_headers):
    response = None
    try:
        request = client.build_request(
            "POST", url + "/chat/completions", headers=request_headers, json=body.model_dump()
        )
        response = await send_until_disconnect(client, request, incoming)
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise ValueError("Streaming response required")
    except BaseException as exc:
        with anyio.CancelScope(shield=True):
            if response is not None:
                await response.aclose()
            await client.aclose()
        if isinstance(exc, (httpx.HTTPError, ValueError)):
            raise HTTPException(502, "Local model completion could not start") from None
        raise

    async def forward():
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > 8 * 1024 * 1024:
                    raise ValueError("Stream too large")
                yield chunk
        except (httpx.HTTPError, ValueError):
            yield b'data: {"error":"Local model stream failed"}\n\n'
        finally:
            with anyio.CancelScope(shield=True):
                await response.aclose()
                await client.aclose()

    return StreamingResponse(forward(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
