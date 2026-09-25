"""Local browser/worker agent lifecycle smoke with a fake provider; no inference."""

import json
import os
import socket
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

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"fake-local"}]}')

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for part in ["# Agent report\n\n", "A fake local observation for the lifecycle test."]:
                self.wfile.write(
                    ("data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n").encode()
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")

    with (
        ThreadingHTTPServer(("127.0.0.1", 0), Provider) as provider,
        tempfile.TemporaryDirectory(prefix="ai-station-agents-") as temporary,
    ):
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        root = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "backend"),
            "AI_STATION_DATA_DIR": str(root / "data"),
            "AI_STATION_DATA_HOST_PATH": str(root / "data"),
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_LLM_BASE_URL": f"http://127.0.0.1:{provider.server_port}/v1",
            "AI_STATION_LLM_MODEL": "fake-local",
            "AI_STATION_LLM_API_KEY": "",
            "AI_STATION_RUNNER_SOCKET": str(root / "absent.sock"),
            "AI_STATION_FRONTEND_DIST": str(ROOT / "frontend/dist"),
        }
        processes = []
        with (root / "server.log").open("w+") as log:

            def launch(*args):
                process = subprocess.Popen(
                    [sys.executable, "-m", *args], cwd=ROOT, env=env, stdout=log, stderr=log
                )
                processes.append(process)
                return process

            def start_api():
                process = launch("uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port))
                for _ in range(200):
                    try:
                        if httpx.get(url + "/api/health", trust_env=False).status_code == 200:
                            return process
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError("API did not start")

            try:
                api = start_api()
                launch("app.worker_main")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url + "/#/agents")
                    page.get_by_role("textbox", name="Instruction", exact=True).fill(
                        "Every morning summarize remembered observations"
                    )
                    page.get_by_role("combobox", name="Local model", exact=True).fill("fake-local")
                    page.get_by_role("button", name="Create draft").click()
                    expect(page.get_by_role("heading", name="Definition")).to_be_visible()
                    expect(page.get_by_role("button", name="Run now")).to_be_disabled()
                    agent_url = page.url
                    agent_id = agent_url.rsplit("/", 1)[1]
                    expect(page.get_by_role("textbox", name="Cron expression (UTC)")).to_have_value(
                        "0 8 * * *"
                    )
                    page.get_by_role("button", name="Enable saved definition").click()
                    expect(page.get_by_role("button", name="Pause agent")).to_be_visible()
                    page.get_by_role("button", name="Run now").click()
                    expect(page.get_by_text("succeeded", exact=True).first).to_be_visible(timeout=20000)
                    run_id = page.url.rsplit("/", 1)[1]
                    artifacts = httpx.get(url + "/api/artifacts", params={"run_id": run_id}).json()
                    assert len(artifacts) == 1 and artifacts[0]["type"] == "markdown"
                    page.goto(agent_url)
                    expect(page.get_by_text("succeeded", exact=True)).to_be_visible()
                    page.get_by_role("button", name="Pause agent").click()
                    expect(page.get_by_role("button", name="Enable saved definition")).to_be_visible()
                    api.terminate()
                    api.wait(timeout=10)
                    start_api()
                    page.goto(agent_url)
                    expect(page.get_by_role("button", name="Run now")).to_be_disabled()
                    expect(page.get_by_text("succeeded", exact=True)).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-agent-detail.png", full_page=True)
                    page.get_by_role("link", name="Inspect this agent's memory").click()
                    expect(page.get_by_role("combobox", name="Scope", exact=True)).to_have_value("agent")
                    expect(page.get_by_role("textbox", name="Scope ID", exact=True)).to_have_value(agent_id)
                    page.goto(agent_url)
                    page.get_by_role("button", name="Duplicate as draft").click()
                    expect(
                        page.get_by_role(
                            "heading", name="Every morning summarize remembered observations (copy)"
                        )
                    ).to_be_visible()
                    expect(page.get_by_role("button", name="Run now")).to_be_disabled()
                    page.get_by_role("link", name="All agents").click()
                    page.screenshot(path="/tmp/ai-station-agents.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path="/tmp/ai-station-agents-mobile.png", full_page=True)
                    assert not errors, errors
                    browser.close()
            except Exception:
                log.flush()
                print(Path(log.name).read_text()[-8000:])
                raise
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                provider.shutdown()
    print(
        "PASS: agent draft, review, enable, worker execution, report artifact, pause, restart, scoped memory, duplicate and mobile layout"
    )


if __name__ == "__main__":
    main()
