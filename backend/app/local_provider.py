"""OpenAI-compatible chat transport; endpoints come from administrator configuration."""

import ipaddress
import json
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.providers import ProviderError

_PRIVATE = [
    ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
]


def validate_endpoint(raw: str, location: str) -> str:
    raw = (raw or "").strip().rstrip("/")
    try:
        url = urlsplit(raw)
        _ = url.port
    except ValueError as exc:
        raise ProviderError("The configured model URL is invalid") from exc
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ProviderError("Configure an HTTP(S) model endpoint without embedded credentials")
    host = url.hostname.lower()
    if location == "local":
        if url.scheme not in {"http", "https"}:
            raise ProviderError("Configure a local HTTP(S) model endpoint without embedded credentials")
        if host not in {"localhost", "host.docker.internal"}:
            try:
                address = ipaddress.ip_address(url.hostname)
            except ValueError as exc:
                raise ProviderError(
                    "Use localhost, host.docker.internal, or a private IP for local chat"
                ) from exc
            if not address.is_loopback and not any(address in network for network in _PRIVATE):
                raise ProviderError("External model endpoints require an explicit external provider")
        return raw
    if location != "external":
        raise ProviderError("Unknown chat provider location")
    if url.scheme != "https":
        raise ProviderError("External chat providers require HTTPS without embedded credentials")
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        raise ProviderError("External chat providers cannot target local hostnames")
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        return raw
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ProviderError("External chat providers cannot target private addresses")
    return raw


def local_endpoint() -> str:
    settings = get_settings()
    raw = (
        settings.llm_host_base_url
        if settings.llm_transport == "runner" and settings.llm_host_base_url
        else settings.llm_base_url
    )
    return validate_endpoint(raw, "local")


def model_endpoint(model, session=None):
    if not model.startswith("llamacpp:"):
        return local_endpoint()
    from app.db import session_factory
    from app.llama import model_endpoint as resolve

    if session is not None:
        return resolve(model, session, allow_pending=True)
    with session_factory()() as current:
        return resolve(model, current)


class LocalChatProvider:
    key = "local-openai-compatible"

    @staticmethod
    def headers():
        key = get_settings().llm_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    @staticmethod
    def connection(*, asynchronous=False, managed=False, runner=None):
        settings = get_settings()
        if runner is None:
            runner = managed or settings.llm_transport == "runner"
        if runner:
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
        return discover_models(endpoint, headers=headers, connection=self.connection())

    async def stream(
        self,
        *,
        endpoint: str,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        headers=None,
        location: str = "local",
        tools: list[dict] | None = None,
        on_tool_calls=None,
    ):
        managed = model.startswith("llamacpp:")
        if managed and location != "local":
            raise ProviderError("Owned llama.cpp models require the local provider")
        original = endpoint
        use_runner = managed or (
            location == "local" and get_settings().llm_transport == "runner" and original == local_endpoint()
        )
        if managed:
            instance_id = original.removeprefix("llamacpp:")
            endpoint, headers = "http://runner/v1/llama/" + instance_id, {}
            model = instance_id
        elif headers is None:
            if original != model_endpoint(model):
                raise ProviderError("The configured endpoint changed after this run was queued")
            endpoint, headers = self.request_target(original)
        elif use_runner:
            endpoint, headers = self.request_target(original)
        done = False
        body = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools is not None:
            body["tools"] = _validated_tools(tools)
            body["tool_choice"] = "auto"
        tool_acc: dict[int, dict[str, str]] = {}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300, connect=10),
                trust_env=False,
                follow_redirects=False,
                **self.connection(asynchronous=True, managed=managed, runner=use_runner),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint + "/chat/completions",
                    headers=headers,
                    json=body,
                ) as response:
                    response.raise_for_status()
                    # Bound protocol records even if a broken server omits newlines.
                    pending = ""
                    finished = False
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
                                done = True
                                finished = True
                                break
                            chunk = json.loads(data)
                            if chunk.get("error"):
                                raise ProviderError("The local provider reported an error")
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            choice = choices[0]
                            done = done or choice.get("finish_reason") is not None
                            delta = choice.get("delta") or {}
                            for item in delta.get("tool_calls") or []:
                                _accumulate_tool_delta(tool_acc, item)
                            content = delta.get("content")
                            if content is not None:
                                if not isinstance(content, str):
                                    raise ProviderError("Unsupported provider content format")
                                if content:
                                    yield content
                        if finished:
                            break
            if tool_acc:
                assembled = [_completed_tool_call(tool_acc[index]) for index in sorted(tool_acc)]
                if on_tool_calls is None:
                    raise ProviderError("Provider returned tool calls that this consumer cannot use")
                on_tool_calls(assembled)
                return
            if not done:
                raise ProviderError("Provider stream ended before completion")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ProviderError("Completion failed or returned an invalid stream") from exc


def _validated_tools(tools):
    if not isinstance(tools, list) or not tools or len(tools) > 8:
        raise ProviderError("Invalid tool list")
    for spec in tools:
        if not isinstance(spec, dict) or spec.get("type") != "function":
            raise ProviderError("Invalid tool list")
        function = spec.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ProviderError("Invalid tool list")
    return tools


def _accumulate_tool_delta(acc: dict[int, dict[str, str]], item) -> None:
    if not isinstance(item, dict) or set(item) - {"index", "id", "type", "function"}:
        raise ProviderError("Unsupported provider tool-call format")
    if item.get("type") not in {None, "function"}:
        raise ProviderError("Unsupported provider tool-call format")
    index = item.get("index", 0)
    if not isinstance(index, int) or index < 0 or index > 7:
        raise ProviderError("Unsupported provider tool-call format")
    slot = acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if "id" in item:
        if not isinstance(item["id"], str) or len(item["id"]) > 80:
            raise ProviderError("Unsupported provider tool-call format")
        slot["id"] = item["id"]
    function = item.get("function")
    if function is None:
        return
    if not isinstance(function, dict) or set(function) - {"name", "arguments"}:
        raise ProviderError("Unsupported provider tool-call format")
    if "name" in function:
        if not isinstance(function["name"], str) or len(slot["name"]) + len(function["name"]) > 80:
            raise ProviderError("Unsupported provider tool-call format")
        slot["name"] += function["name"]
    if "arguments" in function:
        if (
            not isinstance(function["arguments"], str)
            or len(slot["arguments"]) + len(function["arguments"]) > 4000
        ):
            raise ProviderError("Unsupported provider tool-call format")
        slot["arguments"] += function["arguments"]


def _completed_tool_call(slot: dict[str, str]) -> dict:
    if not slot["name"]:
        raise ProviderError("Provider returned an incomplete tool call")
    return {"id": slot["id"], "name": slot["name"], "arguments": slot["arguments"] or "{}"}


def discover_models(
    endpoint: str, *, headers: dict | None = None, connection: dict | None = None
) -> list[str]:
    try:
        with httpx.Client(timeout=8, trust_env=False, follow_redirects=False, **(connection or {})) as client:
            with client.stream("GET", endpoint + "/models", headers=headers or {}) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise ProviderError("Model discovery response is too large")
        payload = json.loads(data)
        return sorted({item["id"] for item in payload["data"] if isinstance(item.get("id"), str)})
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("Model discovery failed; check the endpoint and server logs") from exc
