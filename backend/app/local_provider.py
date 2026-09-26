"""Local OpenAI-compatible provider; endpoints come only from administrator configuration."""

import ipaddress
import json
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.providers import ProviderError


def local_endpoint() -> str:
    settings = get_settings()
    raw = (
        settings.llm_host_base_url
        if settings.llm_transport == "runner" and settings.llm_host_base_url
        else settings.llm_base_url
    ).rstrip("/")
    try:
        url = urlsplit(raw)
        _ = url.port
    except ValueError as exc:
        raise ProviderError("The configured local model URL is invalid") from exc
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ProviderError("Configure a local HTTP(S) model endpoint without embedded credentials")
    if url.hostname not in {"localhost", "host.docker.internal"}:
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError as exc:
            raise ProviderError(
                "Use localhost, host.docker.internal, or a private IP for local chat"
            ) from exc
        private_networks = [
            ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
        ]
        if not address.is_loopback and not any(address in network for network in private_networks):
            raise ProviderError("External model endpoints are not enabled for local chat")
    return raw


class LocalChatProvider:
    key = "local-openai-compatible"

    @staticmethod
    def headers():
        key = get_settings().llm_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    @staticmethod
    def connection(*, asynchronous=False):
        settings = get_settings()
        if settings.llm_transport == "runner":
            transport = httpx.AsyncHTTPTransport if asynchronous else httpx.HTTPTransport
            return {"transport": transport(uds=settings.runner_socket)}
        return {}

    @staticmethod
    def request_target(endpoint):
        if get_settings().llm_transport == "runner":
            return "http://runner/v1/llm", {"X-AI-Station-Endpoint": endpoint}
        return endpoint, LocalChatProvider.headers()

    def models(self) -> list[str]:
        endpoint, headers = self.request_target(local_endpoint())
        try:
            with httpx.Client(
                timeout=8, trust_env=False, follow_redirects=False, **self.connection()
            ) as client:
                with client.stream("GET", endpoint + "/models", headers=headers) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 1024 * 1024:
                            raise ProviderError("Model discovery response is too large")
            payload = json.loads(data)
            return sorted({item["id"] for item in payload["data"] if isinstance(item.get("id"), str)})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("Local model discovery failed; check the endpoint and server logs") from exc

    async def stream(
        self, *, endpoint: str, messages: list[dict], model: str, temperature: float, max_tokens: int
    ):
        if endpoint != local_endpoint():
            raise ProviderError("The configured endpoint changed after this run was queued")
        endpoint, headers = self.request_target(endpoint)
        done = False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300, connect=10),
                trust_env=False,
                follow_redirects=False,
                **self.connection(asynchronous=True),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint + "/chat/completions",
                    headers=headers,
                    json={
                        "messages": messages,
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": True,
                    },
                ) as response:
                    response.raise_for_status()
                    # Bound protocol records even if a broken server omits newlines.
                    pending = ""
                    async for text in response.aiter_text():
                        pending += text
                        if len(pending) > 1024 * 1024:
                            raise ProviderError("Provider stream record exceeds the size limit")
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            chunk = json.loads(data)
                            if chunk.get("error"):
                                raise ProviderError("The local provider reported an error")
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            choice = choices[0]
                            done = done or choice.get("finish_reason") is not None
                            content = (choice.get("delta") or {}).get("content")
                            if content is not None:
                                if not isinstance(content, str):
                                    raise ProviderError("Unsupported provider content format")
                                if content:
                                    yield content
            if not done:
                raise ProviderError("Provider stream ended before completion")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ProviderError("Local completion failed or returned an invalid stream") from exc
