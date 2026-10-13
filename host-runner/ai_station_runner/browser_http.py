"""Credential-free, pinned public GET broker for the isolated browser workload."""

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from ai_station_runner.browser_renderer import MAX_RESPONSE, RESPONSE_HEADERS
from ai_station_runner.public_http import REDIRECTS, pinned_request, public_addresses, public_url


@dataclass
class BrowserBudget:
    remaining: int = 8 * 1024 * 1024
    requests: int = 60
    deadline: float = field(default_factory=lambda: time.monotonic() + 45)


async def fetch_resource(url, budget):
    url = public_url(url)
    if not url:
        raise ValueError("Browser requires public HTTP URLs without credentials")
    budget.requests -= 1
    if budget.requests < 0 or budget.remaining <= 0:
        raise ValueError("Browser network budget exceeded")
    remaining_time = min(15, budget.deadline - time.monotonic())
    if remaining_time <= 0:
        raise ValueError("Browser network deadline exceeded")
    async with asyncio.timeout(remaining_time):
        addresses = await asyncio.to_thread(public_addresses, urlsplit(url).hostname)
        for index, address in enumerate(addresses):
            target, authority, extensions = pinned_request(url, address)
            try:
                async with httpx.AsyncClient(
                    timeout=remaining_time,
                    trust_env=False,
                    follow_redirects=False,
                    headers={"User-Agent": "AI-Station-browser/1", "Accept": "*/*"},
                ) as client:
                    async with client.stream(
                        "GET", target, headers=authority, extensions=extensions
                    ) as response:
                        headers = {
                            key: value for key, value in response.headers.items() if key in RESPONSE_HEADERS
                        }
                        if response.status_code in REDIRECTS:
                            location = public_url(urljoin(url, response.headers.get("location", "")))
                            if not response.headers.get("location") or not location:
                                raise ValueError("Browser redirect targeted a non-public URL")
                            # Reject private redirect DNS before fulfilling the response.
                            await asyncio.to_thread(public_addresses, urlsplit(location).hostname)
                            headers["location"] = location
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            if len(chunk) > budget.remaining:
                                budget.remaining = 0
                                raise ValueError("Browser resource exceeded its byte limit")
                            budget.remaining -= len(chunk)
                            if len(body) + len(chunk) > MAX_RESPONSE:
                                raise ValueError("Browser resource exceeded its byte limit")
                            body.extend(chunk)
                        return response.status_code, headers, bytes(body)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
    raise ValueError("Browser could not connect")
