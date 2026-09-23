"""OpenAI-compatible chat providers. The chat domain is not bound to one runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx

from app.config import get_settings


class ProviderError(Exception):
    pass


def _headers() -> dict[str, str]:
    key = get_settings().llm_api_key
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def list_models() -> list[dict]:
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + "/models"
    try:
        response = httpx.get(url, headers=_headers(), timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(str(exc)) from exc
    payload = response.json()
    return list(payload.get("data") or [])


def stream_chat(
    messages: list[dict],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Iterator[str]:
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    try:
        with httpx.stream("POST", url, json=body, headers=_headers(), timeout=120.0) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                import json

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield content
    except httpx.HTTPError as exc:
        raise ProviderError(str(exc)) from exc


async def astream_chat(
    messages: list[dict],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    import json

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=body, headers=_headers()) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
    except httpx.HTTPError as exc:
        raise ProviderError(str(exc)) from exc


def complete_chat(
    messages: list[dict],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    return "".join(stream_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens))
