"""Internal interactive renderer for a network-disabled optional workload image.

This is not a Host Runner endpoint. Native ownership, archive sourcing, action
receipts, permissions, cancellation and worker adoption must precede publication.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys

if __package__:
    from .site_preview_protocol import (
        MAX_ACTIONS,
        MAX_FRAME,
        MAX_LINE,
        ORIGIN,
        action_request,
        open_request,
        resource_path,
        resource_response,
    )
else:
    from site_preview_protocol import (
        MAX_ACTIONS,
        MAX_FRAME,
        MAX_LINE,
        ORIGIN,
        action_request,
        open_request,
        resource_path,
        resource_response,
    )


def message(payload):
    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(line) > MAX_LINE:
        raise ValueError("Preview output exceeded its protocol limit")
    print(line, flush=True)


async def receive():
    line = await asyncio.to_thread(sys.stdin.readline, MAX_LINE + 1)
    if not line:
        raise EOFError("Preview input closed")
    if len(line) > MAX_LINE or not line.endswith("\n"):
        raise ValueError("Invalid preview protocol line")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Preview protocol requires objects")
    return value


class Input:
    def __init__(self):
        self.actions = asyncio.Queue(maxsize=2)
        self.pending = {}
        self.requests = 0
        self.remaining = 128 * 1024 * 1024

    async def read(self):
        try:
            while True:
                value = await receive()
                if value.get("kind") == "resource":
                    request_id = value.get("id")
                    if type(request_id) is not int or request_id not in self.pending:
                        raise ValueError("Unexpected preview resource identity")
                    body = resource_response(value, request_id)
                    self.remaining -= len(body)
                    if self.remaining < 0:
                        raise ValueError("Preview session resource budget exceeded")
                    future = self.pending[request_id]
                    if future.done():
                        raise ValueError("Repeated preview resource response")
                    future.set_result((value, body))
                elif value == {"kind": "close"}:
                    return
                elif value.get("kind") == "action":
                    self.actions.put_nowait(value)
                else:
                    raise ValueError("Unsupported preview protocol message")
        except EOFError:
            return
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(EOFError("Preview resource channel closed"))

    async def fetch(self, path, *, document=False):
        self.requests += 1
        if self.requests > 2048:
            raise ValueError("Preview session request budget exceeded")
        request_id = self.requests
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        message({"event": "fetch", "id": request_id, "path": path, "document": document})
        try:
            return await asyncio.wait_for(future, timeout=15)
        finally:
            self.pending.pop(request_id, None)

    async def next_action(self, reader):
        action = asyncio.create_task(self.actions.get())
        done, _ = await asyncio.wait({action, reader}, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            action.cancel()
            await asyncio.gather(action, return_exceptions=True)
            reader.result()
            return None
        return action.result()


async def apply_action(page, action, entry):
    kind = action["kind"]
    if kind == "reset":
        await page.goto(ORIGIN + "/" + entry, wait_until="domcontentloaded", timeout=15_000)
    elif kind == "click":
        await page.mouse.click(action["x"], action["y"])
    elif kind == "text":
        await page.keyboard.insert_text(action["text"])
    elif kind == "key":
        await page.keyboard.press(action["key"])
    elif kind == "scroll":
        await page.mouse.wheel(action["delta_x"], action["delta_y"])
    elif kind != "snapshot":
        raise ValueError("Unsupported preview action")


class Session:
    def __init__(self, config):
        self.config = config
        self.revision = 0
        self.blocked = 0
        self.seen = {}
        self.last_frame = None
        self.remaining_frames = 128 * 1024 * 1024

    async def frame(self, page, action_id=None):
        await page.wait_for_timeout(150)
        png = await page.screenshot(type="png", animations="disabled", timeout=5000)
        if len(png) > MAX_FRAME or len(png) > self.remaining_frames:
            raise ValueError("Preview frame budget exceeded")
        self.remaining_frames -= len(png)
        title = "".join(c for c in (await page.title())[:300] if ord(c) >= 32 and ord(c) != 127)
        self.last_frame = {
            "event": "frame",
            "action_id": action_id,
            "revision": self.revision,
            "width": self.config["width"],
            "height": self.config["height"],
            "path": resource_path(page.url),
            "title": title,
            "blocked_requests": self.blocked,
            "png": base64.b64encode(png).decode(),
        }
        message(self.last_frame)

    async def action(self, page, value):
        request = action_request(value, self.config["width"], self.config["height"])
        action_id = request["id"]
        previous = self.seen.get(action_id)
        if previous is not None:
            if previous == request and self.last_frame and self.last_frame["action_id"] == action_id:
                message(self.last_frame)
            else:
                message(
                    {
                        "event": "rejected",
                        "action_id": action_id,
                        "revision": self.revision,
                        "reason": "receipt_conflict",
                    }
                )
            return
        if request["expected_revision"] != self.revision or self.revision >= MAX_ACTIONS:
            message(
                {
                    "event": "rejected",
                    "action_id": action_id,
                    "revision": self.revision,
                    "reason": "stale_revision",
                }
            )
            return
        if resource_path(page.url) is None and request["action"]["kind"] != "reset":
            message(
                {
                    "event": "rejected",
                    "action_id": action_id,
                    "revision": self.revision,
                    "reason": "navigation_blocked",
                }
            )
            return
        # Reserve the receipt before side effects. Failure ends the session;
        # neither the native parent nor this renderer may replay uncertain work.
        self.seen[action_id] = request
        await apply_action(page, request["action"], self.config["entry"])
        self.revision += 1
        await self.frame(page, action_id)


async def render(config):
    from playwright.async_api import async_playwright

    incoming = Input()
    reader = asyncio.create_task(incoming.read())
    session = Session(config)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path="/usr/bin/chromium",
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": config["width"], "height": config["height"]},
                    service_workers="block",
                    accept_downloads=False,
                    permissions=[],
                )

                async def close_socket(socket):
                    session.blocked += 1
                    await socket.close()

                await context.route_web_socket("**/*", close_socket)
                page = await context.new_page()
                context.on("page", lambda popup: asyncio.create_task(popup.close()))
                page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
                page.on("download", lambda download: asyncio.create_task(download.cancel()))
                cdp = await context.new_cdp_session(page)

                async def route_request(event):
                    request, request_id = event["request"], event["requestId"]
                    path = resource_path(request.get("url"))
                    if request.get("method") != "GET" or path is None:
                        session.blocked += 1
                        await cdp.send(
                            "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                        )
                        return
                    try:
                        reply, _ = await incoming.fetch(
                            path, document=event.get("resourceType") == "Document"
                        )
                        await cdp.send(
                            "Fetch.fulfillRequest",
                            {
                                "requestId": request_id,
                                "responseCode": reply["status"],
                                "responseHeaders": [{"name": "content-type", "value": reply["content_type"]}],
                                "body": reply["body"],
                            },
                        )
                    except (ValueError, TimeoutError, EOFError):
                        session.blocked += 1
                        await cdp.send(
                            "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                        )

                cdp.on("Fetch.requestPaused", route_request)
                await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
                response = await page.goto(
                    ORIGIN + "/" + config["entry"], wait_until="domcontentloaded", timeout=20_000
                )
                if response is None or response.status != 200:
                    raise ValueError("Preview entry was unavailable")
                await session.frame(page)
                while value := await incoming.next_action(reader):
                    await session.action(page, value)
            finally:
                await browser.close()
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


async def main():
    config = open_request(await receive())
    async with asyncio.timeout(config["max_seconds"]):
        await render(config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("Preview stopped: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
