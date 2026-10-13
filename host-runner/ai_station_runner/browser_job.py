"""Managed browser wrapper; no credentials or filesystem enter its container."""

import asyncio
import base64
import fcntl
import json
import signal
import sys
import time
from contextlib import suppress
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ai_station_runner.browser_http import BrowserBudget, fetch_resource
from ai_station_runner.browser_renderer import MAX_LINE, MAX_RESPONSE
from ai_station_runner.browser_runs import (
    BrowserRequest,
    container_identity,
    directory,
    docker,
    inspect_container,
    load_request,
    owned_path,
    save,
    stop_containers,
)
from ai_station_runner.public_http import public_url


async def render_page(run_id, saved, index, url):
    root = directory(run_id)
    with (root / "containers.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (root / "cancel.json").exists():
            raise InterruptedError("Browser canceled before container creation")
        name, labels = container_identity(saved, index)
        manifest = root / f"container-{index}.json"
        if manifest.exists():
            raise ValueError("Browser container dispatch is never replayed")
        save(manifest, {"state": "creating", "id": None})
        args = ["create", "--pull", "never", "--name", name]
        for key, value in labels.items():
            args += ["--label", f"{key}={value}"]
        args += [
            "--interactive",
            "--init",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            saved["image"],
        ]
        cid = docker(args)
        item = inspect_container(saved, index, cid)
        if item is None:
            raise ValueError("Browser creation identity could not be confirmed")
        save(manifest, {"state": "created", "id": item["Id"]})
        if (root / "cancel.json").exists():
            raise InterruptedError("Browser canceled before rendering")
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "start",
        "--attach",
        "--interactive",
        cid,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=MAX_LINE + 1,
    )
    stderr_task = asyncio.create_task(read_stderr(proc.stderr))
    budget = BrowserBudget()
    requests = []
    result = None
    try:
        async with asyncio.timeout(55):
            proc.stdin.write((json.dumps({"url": url}) + "\n").encode())
            await proc.stdin.drain()
            while line := await proc.stdout.readline():
                if len(line) > MAX_LINE:
                    raise ValueError("Browser output exceeded its limit")
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid browser result")
                if payload.get("event") == "fetch":
                    if (
                        set(payload) != {"event", "id", "url", "method"}
                        or payload["method"] != "GET"
                        or type(payload["id"]) is not int
                        or payload["id"] != len(requests) + 1
                        or len(requests) >= 60
                    ):
                        raise ValueError("Invalid browser GET request")
                    request_url = payload["url"]
                    note = {"url": request_url, "method": "GET"}
                    try:
                        status, headers, body = await fetch_resource(request_url, budget)
                        note["status"] = status
                    except (ValueError, OSError, TimeoutError, httpx.HTTPError) as exc:
                        status, headers, body = (
                            403,
                            {"content-type": "text/plain"},
                            b"Resource blocked or unavailable",
                        )
                        note.update(status=status, error=type(exc).__name__)
                    requests.append(note)
                    print(json.dumps({"event": "browser.request.completed", **note}), flush=True)
                    proc.stdin.write(
                        (
                            json.dumps(
                                {
                                    "id": payload["id"],
                                    "status": status,
                                    "headers": headers,
                                    "body": base64.b64encode(body).decode(),
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                    await proc.stdin.drain()
                elif payload.get("event") == "rendered":
                    if result is not None or set(payload) != {
                        "event",
                        "url",
                        "title",
                        "status",
                        "text",
                        "truncated",
                        "links",
                        "screenshot",
                        "width",
                        "height",
                        "requests",
                        "blocked_request_count",
                    }:
                        raise ValueError("Invalid or duplicate browser completion")
                    if (
                        not public_url(payload["url"])
                        or len(payload["text"]) > 8000
                        or len(payload["title"]) > 200
                    ):
                        raise ValueError("Invalid browser page metadata")
                    if (
                        payload["width"] != 1240
                        or payload["height"] != 800
                        or not 200 <= payload["status"] < 300
                    ):
                        raise ValueError("Invalid browser screenshot dimensions or status")
                    png = base64.b64decode(payload.pop("screenshot"), validate=True)
                    if len(png) > MAX_RESPONSE:
                        raise ValueError("Browser screenshot exceeded its limit")
                    import io

                    from PIL import Image

                    with Image.open(io.BytesIO(png)) as image:
                        if image.format != "PNG" or image.size != (1240, 800):
                            raise ValueError("Invalid browser screenshot")
                        image.verify()
                    screenshot = owned_path(f"runtime/browser/{run_id}/page-{index}.png")
                    screenshot.write_bytes(png)
                    screenshot.chmod(0o600)
                    payload["screenshot_path"] = f"runtime/browser/{run_id}/page-{index}.png"
                    payload["links"] = [
                        row
                        for row in payload["links"][:30]
                        if isinstance(row, dict)
                        and public_url(row.get("url"))
                        and urlsplit(row["url"]).hostname == urlsplit(payload["url"]).hostname
                    ][:15]
                    result = {**payload, "requests": requests, "untrusted": True, "bounded": True}
                else:
                    raise ValueError("Browser rendering did not complete")
            if await proc.wait() != 0 or result is None:
                raise ValueError("Browser process failed or returned no page")
            return result
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.returncode is None:
            proc.terminate()
            with suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), 2)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        stderr_task.cancel()
        with suppress(asyncio.CancelledError):
            await stderr_task


async def read_stderr(stream):
    # Drain without persisting arbitrary browser diagnostics/URLs into run logs.
    while await stream.read(65536):
        pass


async def main(run_id):
    run_id = str(UUID(run_id))
    root = directory(run_id)
    saved = load_request(run_id)
    request = BrowserRequest.model_validate(saved["request"])
    if str(request.run_id) != run_id or not {"browser", "network_read"}.issubset(request.permissions):
        raise PermissionError("Browser request ownership or permission mismatch")
    pages = []
    try:
        async with asyncio.timeout(request.maximum_runtime):
            for index, url in enumerate(request.urls):
                print(json.dumps({"event": "browser.page.started", "index": index, "url": url}), flush=True)
                pages.append(await render_page(run_id, saved, index, url))
                if not stop_containers(run_id):
                    raise ValueError("Browser completion requires inspection")
        save(
            root / "report.json",
            {"run_id": run_id, "urls": request.urls, "pages": pages, "captured_at": time.time()},
        )
        print(json.dumps({"event": "browser.completed", "pages": len(pages)}), flush=True)
    finally:
        stop_containers(run_id)


if __name__ == "__main__":

    def interrupted(*_):
        raise InterruptedError("Browser canceled")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(180)
    try:
        asyncio.run(main(sys.argv[1]))
    except Exception as exc:
        print(
            f"Browser failed: {type(exc).__name__}. Inspect Run and owned container state.", file=sys.stderr
        )
        sys.exit(1)
    finally:
        signal.alarm(0)
