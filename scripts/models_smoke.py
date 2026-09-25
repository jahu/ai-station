"""Opt-in Models browser/worker/UDS smoke with disposable model files."""

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

    with tempfile.TemporaryDirectory(prefix="ai-station-models-") as temporary:
        root = Path(temporary)
        models = root / "models/llm"
        models.mkdir(parents=True)
        source = models / "Qwen-test-Q4_K_M.gguf"
        source.write_bytes(b"fake fixture; never loaded")
        before = source.stat()
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
            "AI_STATION_MODEL_ROOTS": str(models),
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
                    page.goto(url + "/#/models")
                    page.get_by_role("button", name="Discover models").click()
                    expect(page.get_by_text("succeeded", exact=True).first).to_be_visible(timeout=20000)
                    page.get_by_role("link", name="Models", exact=True).click()
                    page.get_by_role("heading", name=source.name).click()
                    expect(page.get_by_role("heading", name="File observation")).to_be_visible()
                    expect(page.get_by_text("present", exact=True)).to_be_visible()
                    page.reload()
                    expect(page.get_by_role("heading", name=source.name)).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-model-detail.png", full_page=True)
                    page.get_by_role("link", name="All models").click()
                    page.get_by_role("button", name="Images", exact=True).click()
                    expect(page.get_by_role("heading", name="No model files in this view")).to_be_visible()
                    page.get_by_role("button", name="LLM", exact=True).click()
                    expect(page.get_by_role("heading", name=source.name)).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-models.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path="/tmp/ai-station-models-mobile.png", full_page=True)
                    assert not errors, errors
                    browser.close()
                assert source.read_bytes() == b"fake fixture; never loaded"
                assert source.stat().st_mtime_ns == before.st_mtime_ns
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    print(
        "PASS: browser discovery Run, native UDS scan, durable file detail, category filters and mobile width; model unchanged"
    )


if __name__ == "__main__":
    main()
