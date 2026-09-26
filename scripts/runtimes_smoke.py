"""Read-only runtime browser/worker/UDS smoke with temporary application data."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main():
    from playwright.sync_api import expect, sync_playwright

    with tempfile.TemporaryDirectory(prefix="ai-station-runtimes-") as temporary:
        root = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT / "host-runner")]),
            "AI_STATION_DATA_DIR": str(root / "data"),
            "AI_STATION_DATA_HOST_PATH": str(root / "data"),
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_LLM_API_KEY": "",
            "AI_STATION_LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "AI_STATION_RUNNER_SOCKET": str(root / "runtime/runner.sock"),
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

            try:
                launch("ai_station_runner.main")
                launch("uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port))
                for _ in range(200):
                    try:
                        if httpx.get(url + "/api/health", trust_env=False).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("API did not start")
                launch("app.worker_main")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url + "/#/system")
                    page.get_by_role("button", name="Observe runtimes").click()
                    expect(page.get_by_text("succeeded", exact=True).first).to_be_visible(timeout=20000)
                    page.get_by_role("link", name="System", exact=True).click()
                    expect(page.get_by_text("Local compatible endpoint", exact=True)).to_be_visible()
                    expect(
                        page.get_by_text("Endpoint status checks model discovery, not generation.")
                    ).to_be_visible()
                    page.reload()
                    expect(page.get_by_text("Local compatible endpoint", exact=True)).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-runtimes.png", full_page=True)
                    result = httpx.get(url + "/api/runtimes", trust_env=False).json()
                    assert result["latest_scan"]["status"] == "succeeded"
                    assert all(row["ownership"] == "external" for row in result["items"])
                    endpoint = next(row for row in result["items"] if row["endpoint"])
                    assert endpoint["status"] == "unavailable"
                    print(
                        "Observed host runtime families:",
                        sorted({row["runtime_key"] for row in result["items"] if not row["endpoint"]}),
                    )
                    with httpx.Client(base_url=url, trust_env=False) as api:
                        agent = api.post(
                            "/api/agents",
                            json={
                                "name": "Dashboard acceptance agent",
                                "goal": "Fixture only",
                                "model": "not-executed",
                                "trigger": "interval",
                                "interval_seconds": 86400,
                                "enabled": True,
                            },
                        )
                        agent.raise_for_status()
                        conversation = api.post(
                            "/api/chat/conversations",
                            json={
                                "title": "Dashboard acceptance conversation",
                                "model": "not-executed",
                            },
                        )
                        conversation.raise_for_status()
                    page.goto(url + "/#/")
                    expect(page.get_by_role("heading", name="Enabled agents · 1")).to_be_visible()
                    expect(page.get_by_role("heading", name="Upcoming schedules")).to_be_visible()
                    expect(
                        page.get_by_role("link", name="Dashboard acceptance conversation", exact=False)
                    ).to_be_visible()
                    page.get_by_role("link", name="Dashboard acceptance conversation", exact=False).click()
                    expect(page).to_have_url(url + "/#/chat/" + conversation.json()["id"])
                    page.goto(url + "/#/")
                    expect(page.get_by_role("heading", name="Recent artifacts")).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-dashboard.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path="/tmp/ai-station-dashboard-mobile.png", full_page=True)
                    assert not errors, errors
                    browser.close()
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    print(
        "PASS: browser runtime observation, native read-only process discovery, truthful unavailable endpoint, persisted registry and mobile width"
    )


if __name__ == "__main__":
    main()
