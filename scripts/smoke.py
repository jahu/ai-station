"""Opt-in Docker smoke test. Uses fake work and a disposable, owned deployment."""

import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parent.parent


def browser_smoke(url: str):
    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1040})
        page.on("pageerror", lambda error: errors.append(str(error)))
        with page.expect_response("**/api/system/hardware"):
            page.goto(url)
        page.get_by_role("heading", name="Your workspace, in focus.").wait_for()
        page.screenshot(path="/tmp/ai-station-dashboard.png", full_page=True)
        page.keyboard.press("Control+k")
        page.get_by_role("dialog").wait_for()
        page.locator("[cmdk-input]").fill("Runs")
        page.locator("[cmdk-item]").first.click()
        page.get_by_role("heading", name="Every run, accounted for.").wait_for()
        page.get_by_role("link", name="system.self_test", exact=False).click()
        page.get_by_text("run.completed", exact=True).wait_for()
        page.set_viewport_size({"width": 390, "height": 844})
        with page.expect_response("**/api/system/hardware"):
            page.goto(url)
        page.get_by_role("heading", name="Your workspace, in focus.").wait_for()
        page.get_by_role("status").wait_for(state="hidden")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path="/tmp/ai-station-mobile.png", full_page=True)
        assert not errors, errors
        browser.close()
    print("PASS: browser dashboard, command palette, run timeline, mobile layout, no page errors", flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix="ai-station-smoke-") as temporary:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "AI_STATION_DATA_HOST_PATH": temporary,
            "AI_STATION_RUNNER_SOCKET": str(Path(temporary) / "runtime/runner/runner.sock"),
            "AI_STATION_RUNNER_SOCKET_DIR": str(Path(temporary) / "runtime/runner"),
            "AI_STATION_PORT": str(port),
            "AI_STATION_ENABLE_TEST_EXECUTOR": "true",
            "AI_STATION_UID": str(os.getuid()),
            "AI_STATION_GID": str(os.getgid()),
            "COMPOSE_PROJECT_NAME": f"ai-station-smoke-{uuid4().hex[:8]}",
        }
        dev = os.environ.get("AI_STATION_SMOKE_DEV") == "1"
        command = [str(ROOT / "scripts/start.sh"), "--no-build"]
        if dev:
            command.append("--dev")
        process = subprocess.Popen(command, cwd=ROOT, env=env)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 120
                while True:
                    try:
                        response = client.get("/api/health")
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Smoke deployment failed to start")
                    time.sleep(0.5)
                assert "AI Station" in client.get("/").text
                response = client.post("/api/testing/runs", json={"title": "Docker fake executor smoke"})
                response.raise_for_status()
                run_id = response.json()["id"]
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run_id}").json()
                    if run["status"] == "succeeded":
                        break
                    time.sleep(0.5)
                assert run["status"] == "succeeded", run
                assert "run.completed" in client.get(f"/api/runs/{run_id}/stream").text
                assert client.get("/api/system/hardware").status_code == 200
                status = client.get("/api/system/status").json()
                assert any(w["available"] for w in status["workers"])
                assert status["scheduler"]["available"]
                if os.environ.get("AI_STATION_BROWSER_SMOKE") == "1":
                    browser_smoke(f"http://127.0.0.1:{5173 if dev else port}")
                # Restart only this disposable deployment's API container.
                subprocess.run(
                    ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "restart", "ai-station"],
                    cwd=ROOT,
                    env=env,
                    check=True,
                )
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        persisted = client.get(f"/api/runs/{run_id}")
                        if persisted.status_code == 200:
                            assert persisted.json()["status"] == "succeeded"
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("API did not recover after restart")
                print(
                    "PASS: UI, API, native UDS telemetry, worker, fake execution, SSE, restart persistence",
                    flush=True,
                )
        finally:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                process.kill()
                subprocess.run(
                    ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "down"],
                    cwd=ROOT,
                    env=env,
                    check=True,
                )
                raise
        assert not Path(env["AI_STATION_RUNNER_SOCKET"]).exists(), "Runner did not clean up its socket"
        remaining = subprocess.run(
            ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "ps", "-aq"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert not remaining.stdout.strip(), "Smoke containers remain"
        print("PASS: supervisor shutdown cleaned up its runner and containers", flush=True)


if __name__ == "__main__":
    main()
