"""Opt-in browser smoke with isolated local storage and no provider calls."""

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

    with tempfile.TemporaryDirectory(prefix="ai-station-memory-") as temporary:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "backend"),
            "AI_STATION_DATA_DIR": temporary,
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_FRONTEND_DIST": str(ROOT / "frontend/dist"),
            "AI_STATION_RUNNER_SOCKET": temporary + "/absent.sock",
        }
        with (Path(temporary) / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(200):
                    try:
                        if httpx.get(url + "/api/health", trust_env=False).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("API did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url + "/#/memory/new")
                    page.get_by_role("textbox", name="Content", exact=True).fill(
                        "Prefer concise Polish explanations with verifiable examples."
                    )
                    page.get_by_label("Tags", exact=True).fill("language, style")
                    page.get_by_label("Pinned context").check()
                    page.get_by_role("button", name="Save memory").click()
                    expect(page.get_by_role("heading", name="Provenance")).to_be_visible()
                    page.reload()
                    expect(page.get_by_role("textbox", name="Content", exact=True)).to_have_value(
                        "Prefer concise Polish explanations with verifiable examples."
                    )
                    page.screenshot(path="/tmp/ai-station-memory-detail.png", full_page=True)
                    page.get_by_label("Enabled", exact=True).uncheck()
                    page.get_by_role("button", name="Save memory").click()
                    expect(page.get_by_role("button", name="Save memory")).to_be_enabled()
                    page.get_by_role("link", name="All memories").click()
                    expect(page.get_by_role("heading", name="No matching memories")).to_be_visible()
                    page.get_by_label("Include disabled").check()
                    page.get_by_label("Search memory").fill("Polish")
                    expect(
                        page.get_by_text("Prefer concise Polish explanations with verifiable examples.")
                    ).to_be_visible()
                    page.screenshot(path="/tmp/ai-station-memory.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.screenshot(path="/tmp/ai-station-memory-mobile.png", full_page=True)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.get_by_text("Prefer concise Polish explanations with verifiable examples.").click()
                    page.get_by_role("button", name="Delete memory…").click()
                    page.get_by_role("button", name="Permanently delete memory").click()
                    expect(page.get_by_role("heading", name="No matching memories")).to_be_visible()
                    assert not errors, errors
                    browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print(
        "PASS: browser memory CRUD, reload persistence, disable/search, confirmed delete, mobile width; no inference"
    )


if __name__ == "__main__":
    main()
