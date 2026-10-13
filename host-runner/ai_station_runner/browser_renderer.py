"""Fixed read-only renderer inside a network-disabled, mount-free container.

All HTTP is fulfilled through a bounded stdin/stdout protocol. The trusted native
parent must validate each public GET; no direct browser network is permitted.
This module is an internal workload, not a native API or operational agent tool.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from urllib.parse import urlsplit

MAX_RESPONSE = 4 * 1024 * 1024
MAX_LINE = 6 * 1024 * 1024
MAX_REQUESTS = 60
MAX_TEXT = 8000
VIEWPORT = {"width": 1240, "height": 800}
RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "location",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "content-security-policy",
        "cross-origin-resource-policy",
        "cross-origin-opener-policy",
        "cross-origin-embedder-policy",
        "referrer-policy",
    }
)


def message(value):
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if len(text) > MAX_LINE:
        raise ValueError("Browser message exceeded its limit")
    print(text, flush=True)


async def receive():
    line = await asyncio.to_thread(sys.stdin.readline, MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith("\n"):
        raise ValueError("Missing or oversized browser protocol message")
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("Browser protocol requires an object")
    return payload


def response_body(reply, request_id):
    if (
        set(reply) != {"id", "status", "headers", "body"}
        or type(reply["id"]) is not int
        or reply["id"] != request_id
    ):
        raise ValueError("Unexpected browser response")
    if type(reply["status"]) is not int or not 200 <= reply["status"] <= 599:
        raise ValueError("Invalid browser response status")
    headers = reply["headers"]
    if not isinstance(headers, dict) or set(headers) - RESPONSE_HEADERS:
        raise ValueError("Invalid browser response headers")
    if any(
        not isinstance(value, str) or len(value) > 2000 or any(c in value for c in "\r\n")
        for value in headers.values()
    ):
        raise ValueError("Invalid browser response header value")
    if not isinstance(reply["body"], str) or len(reply["body"]) > (MAX_RESPONSE + 2) // 3 * 4:
        raise ValueError("Browser response exceeded its limit")
    body = base64.b64decode(reply["body"], validate=True)
    if len(body) > MAX_RESPONSE:
        raise ValueError("Browser response exceeded its limit")
    return body


async def render(url):
    from playwright.async_api import async_playwright

    lock = asyncio.Lock()
    count = 0

    async def route_request(event):
        nonlocal count
        request = event["request"]
        request_id = event["requestId"]
        # CDP pauses each redirect too. Playwright route fulfillment otherwise
        # lets Chromium attempt the redirect directly (blocked by network=none).
        if (
            request["method"] != "GET"
            or len(request["url"]) > 2000
            or urlsplit(request["url"]).scheme not in {"http", "https"}
        ):
            await cdp.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
            return
        async with lock:
            count += 1
            if count > MAX_REQUESTS:
                await cdp.send(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                )
                return
            message({"event": "fetch", "id": count, "url": request["url"], "method": "GET"})
            reply = await receive()
            response_body(reply, count)
            await cdp.send(
                "Fetch.fulfillRequest",
                {
                    "requestId": request_id,
                    "responseCode": reply["status"],
                    "responseHeaders": [
                        {"name": key, "value": value} for key, value in reply["headers"].items()
                    ],
                    "body": reply["body"],
                },
            )

    async def close_socket(socket):
        await socket.close()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        try:
            context = await browser.new_context(
                viewport=VIEWPORT,
                service_workers="block",
                accept_downloads=False,
                permissions=[],
            )
            await context.route_web_socket("**/*", close_socket)
            page = await context.new_page()
            context.on("page", lambda popup: asyncio.create_task(popup.close()))
            cdp = await context.new_cdp_session(page)
            cdp.on("Fetch.requestPaused", route_request)
            await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if response is None or not 200 <= response.status < 300:
                raise ValueError("Browser page did not return successful public content")
            # A fixed short settling window includes initial client-side rendering.
            await page.wait_for_timeout(1500)
            text = await page.locator("body").inner_text(timeout=5000)
            title = await page.title()
            links = await page.eval_on_selector_all(
                "a[href]", "els => els.slice(0, 30).map(el => ({url:el.href,text:el.innerText.slice(0,200)}))"
            )
            screenshot = await page.screenshot(type="png", full_page=False, timeout=5000)
            if len(screenshot) > MAX_RESPONSE:
                raise ValueError("Browser screenshot exceeded its limit")
            message(
                {
                    "event": "rendered",
                    "url": page.url,
                    "title": title[:200],
                    "status": response.status,
                    "text": text[:MAX_TEXT],
                    "truncated": len(text) > MAX_TEXT,
                    "links": links,
                    "screenshot": base64.b64encode(screenshot).decode("ascii"),
                    "width": VIEWPORT["width"],
                    "height": VIEWPORT["height"],
                    "requests": min(count, MAX_REQUESTS),
                }
            )
        finally:
            await asyncio.wait_for(browser.close(), timeout=3)


async def main():
    async with asyncio.timeout(50):
        request = await receive()
        if set(request) != {"url"} or not isinstance(request["url"], str) or len(request["url"]) > 2000:
            raise ValueError("Browser requires one bounded URL")
        if urlsplit(request["url"]).scheme not in {"http", "https"}:
            raise ValueError("Browser requires an HTTP URL")
        await render(request["url"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # This is a mount-free, credential-free workload; stderr is consumed and
        # redacted by the trusted native parent, never used as execution state.
        print(f"Browser renderer: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        message({"event": "failed", "error": "Browser rendering did not complete"})
        sys.exit(1)
