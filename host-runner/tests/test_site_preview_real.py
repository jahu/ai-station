"""Explicit opt-in renderer acceptance; no native/API capability is published."""

import asyncio
import base64
import io
import json
import os
import subprocess
from uuid import uuid4

import pytest
from ai_station_runner.site_preview_protocol import MAX_LINE

pytestmark = pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_BROWSER_TESTS") != "1", reason="Opt-in isolated Chromium/container acceptance"
)


@pytest.mark.asyncio
async def test_real_offline_preview_modules_click_literal_text_and_receipts():
    from PIL import Image

    tag = os.getenv("AI_STATION_PREVIEW_TEST_IMAGE", "ai-station-site-preview:development")
    metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", tag], text=True))[0]
    assert metadata["Config"]["User"] == "1000:1000"
    assert metadata["Config"]["Labels"]["ai-station.site-preview.protocol"] == "2"
    image = metadata["Id"]
    owner = str(uuid4())
    name = "ai-station-site-preview-qa-" + owner
    assets = {
        "index.html": (
            "text/html",
            b'<html><title>Loading</title><body><button style="position:absolute;left:20px;top:20px;width:180px;height:50px" id="count">Counter</button><input style="position:absolute;left:20px;top:90px;width:250px;height:30px" id="text"><script type="module" src="/app.js"></script></body></html>',
        ),
        "app.js": (
            "text/javascript",
            b"""import {wire} from './counter.js'; wire();
fetch('http://127.0.0.1:8765/api/runs').catch(()=>{});
fetch('/unapproved-post', {method:'POST', body:'blocked'}).catch(()=>{});
new WebSocket('ws://127.0.0.1:8765/blocked');""",
        ),
        "counter.js": (
            "text/javascript",
            b"""export function wire(){let n=0;let input=document.getElementById('text');input.value='';let update=()=>document.title='count='+n+';text='+input.value;document.getElementById('count').onclick=()=>{n++;update()};input.oninput=update;update()}""",
        ),
    }
    process = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        "ai-station.acceptance=" + owner,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "1g",
        "--memory-swap",
        "1g",
        "--cpus",
        "1",
        "--pids-limit",
        "256",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        "--shm-size",
        "128m",
        "-i",
        image,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=MAX_LINE + 1,
        start_new_session=True,
    )
    stderr = asyncio.create_task(process.stderr.read())
    paths = []

    async def send(value):
        process.stdin.write((json.dumps(value) + "\n").encode())
        await process.stdin.drain()

    async def result():
        async with asyncio.timeout(40):
            while line := await process.stdout.readline():
                assert len(line) <= MAX_LINE
                value = json.loads(line)
                if value.get("event") == "fetch":
                    assert set(value) == {"event", "id", "path", "document"}
                    path = value["path"]
                    paths.append(path)
                    content_type, body = assets.get(path, ("text/plain", b"not found"))
                    await send(
                        {
                            "kind": "resource",
                            "id": value["id"],
                            "status": 200 if path in assets else 404,
                            "content_type": content_type,
                            "body": base64.b64encode(body).decode(),
                        }
                    )
                else:
                    if value.get("event") == "frame":
                        with Image.open(
                            io.BytesIO(base64.b64decode(value["png"], validate=True))
                        ) as screenshot:
                            assert screenshot.size == (800, 600) and screenshot.format == "PNG"
                    return value
        raise AssertionError("Preview ended without a bounded response")

    def action(kind, revision, **values):
        return {
            "kind": "action",
            "id": str(uuid4()),
            "expected_revision": revision,
            "action": {"kind": kind, **values},
        }

    try:
        await send({"kind": "open", "entry": "index.html", "width": 800, "height": 600, "max_seconds": 90})
        initial = await result()
        assert (
            initial["event"] == "frame" and initial["revision"] == 0 and initial["title"] == "count=0;text="
        )
        assert initial["blocked_requests"] >= 2
        click = action("click", 0, x=30, y=30)
        await send(click)
        clicked = await result()
        assert clicked["revision"] == 1 and clicked["title"] == "count=1;text="
        await send(click)
        assert await result() == clicked
        await send(action("click", 0, x=30, y=30))
        assert (await result())["reason"] == "stale_revision"
        await send(action("click", 1, x=30, y=100))
        assert (await result())["revision"] == 2
        text = "<script>literal text</script>"
        await send(action("text", 2, text=text))
        typed = await result()
        assert typed["revision"] == 3 and typed["title"] == "count=1;text=" + text
        await send(action("reset", 3))
        reset = await result()
        assert reset["revision"] == 4 and reset["title"] == "count=0;text="
        assert {"index.html", "app.js", "counter.js"} <= set(paths)
        assert "unapproved-post" not in paths and not any("127.0.0.1" in path for path in paths)
        await send({"kind": "close"})
        process.stdin.close()
        assert await asyncio.wait_for(process.wait(), timeout=15) == 0, (await stderr).decode()[-2000:]
        assert subprocess.run(["docker", "container", "inspect", name], capture_output=True).returncode != 0
    finally:
        found = subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True)
        if found.returncode == 0:
            container = json.loads(found.stdout)[0]
            assert (
                container["Config"]["Labels"].get("ai-station.acceptance") == owner
                and container["Image"] == image
            )
            subprocess.run(["docker", "rm", "-f", container["Id"]], check=True, capture_output=True)
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=10)
        if not stderr.done():
            await stderr
