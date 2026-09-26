"""Opt-in local browser smoke with a loopback fake model server; no AI inference."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main():
    from playwright.sync_api import expect, sync_playwright

    stop = threading.Event()
    silent_started = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"fake-local-model"}]}')

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if body["messages"][-1]["content"] == "Wait silently":
                silent_started.set()
                stop.wait(30)
                return
            try:
                for part in ["Hello from ", "**fake local chat**.\n\n", '```python\nprint("hello")\n```']:
                    self.wfile.write(
                        ("data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n").encode()
                    )
                    self.wfile.flush()
                    time.sleep(0.15)
                self.wfile.write(b"data: [DONE]\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

    with (
        ThreadingHTTPServer(("127.0.0.1", 0), Provider) as provider,
        tempfile.TemporaryDirectory(prefix="ai-station-chat-") as temporary,
    ):
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "backend"),
            "AI_STATION_DATA_DIR": temporary,
            "AI_STATION_DATA_HOST_PATH": temporary,
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_LLM_TRANSPORT": "direct",
            "AI_STATION_LLM_BASE_URL": f"http://127.0.0.1:{provider.server_port}/v1",
            "AI_STATION_LLM_MODEL": "fake-local-model",
            "AI_STATION_LLM_API_KEY": "",
            "AI_STATION_FRONTEND_DIST": str(ROOT / "frontend/dist"),
            "AI_STATION_RUNNER_SOCKET": temporary + "/absent.sock",
            "AI_STATION_HEARTBEAT_SECONDS": "1",
        }
        processes = []
        with (Path(temporary) / "server.log").open("w+") as log:

            def start_api():
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.api:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(process)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    try:
                        if httpx.get(url + "/api/health").status_code == 200:
                            return process
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError("API did not start")

            try:
                api_process = start_api()
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "app.worker_main"], cwd=ROOT, env=env, stdout=log, stderr=log
                    )
                )
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1040})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(url + "/#/chat")
                    page.get_by_role("button", name="Create conversation").click()
                    page.get_by_label("Message", exact=True).fill("Hello")
                    page.get_by_role("button", name="Send", exact=True).click()
                    page.get_by_text("fake local chat", exact=True).wait_for(timeout=20000)
                    page.get_by_text("succeeded", exact=True).wait_for()
                    page.screenshot(path="/tmp/ai-station-chat.png", full_page=True)
                    conversation_url = page.url
                    api_process.terminate()
                    api_process.wait(timeout=10)
                    start_api()
                    page.goto(conversation_url)
                    page.get_by_text("fake local chat", exact=True).wait_for()
                    page.get_by_role("button", name="Regenerate last response").click()
                    page.get_by_text("Local AI · Previous response", exact=True).wait_for()
                    page.get_by_text("succeeded", exact=True).nth(1).wait_for(timeout=20000)
                    page.get_by_label("Message", exact=True).fill("Wait silently")
                    page.get_by_role("button", name="Send", exact=True).click()
                    assert silent_started.wait(20), "Fake provider was not called"
                    page.get_by_role("button", name="Stop", exact=True).click()
                    page.get_by_text("canceled", exact=True).wait_for(timeout=10000)
                    conversation_id = conversation_url.rsplit("/", 1)[-1]
                    with httpx.Client(base_url=url, trust_env=False) as api:
                        for index in range(5):
                            queued = api.post(
                                f"/api/chat/conversations/{conversation_id}/messages",
                                json={"content": f"Summary fixture {index}"},
                            )
                            queued.raise_for_status()
                            deadline = time.monotonic() + 20
                            while time.monotonic() < deadline:
                                result = api.get(f"/api/runs/{queued.json()['id']}").json()
                                if result["status"] in {"succeeded", "failed", "canceled"}:
                                    break
                                time.sleep(0.2)
                            assert result["status"] == "succeeded", result
                    page.get_by_text("Conversation memory · Recent messages only", exact=True).click()
                    page.get_by_role("button", name="Update summary", exact=True).click()
                    expect(
                        page.get_by_text("Conversation memory · Summary active", exact=True)
                    ).to_be_visible(timeout=20000)
                    expect(page.get_by_role("link", name="Edit or disable memory")).to_be_visible()
                    with httpx.Client(base_url=url, trust_env=False) as api:
                        summary = api.get(f"/api/chat/conversations/{conversation_id}").json()["summary"]
                        assert summary["enabled"] and summary["source_message_ids"]
                        assert api.get(f"/api/runs/{summary['run_id']}").json()["status"] == "succeeded"
                    page.screenshot(path="/tmp/ai-station-summary.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path="/tmp/ai-station-chat-mobile.png", full_page=True)
                    assert not errors, errors
                    browser.close()
                print(
                    "PASS: local chat discovery, streaming, Markdown, restart persistence, regeneration, silent-provider cancellation, and mobile layout"
                )
            except Exception:
                log.flush()
                print(Path(log.name).read_text()[-8000:])
                raise
            finally:
                stop.set()
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                provider.shutdown()


if __name__ == "__main__":
    main()
