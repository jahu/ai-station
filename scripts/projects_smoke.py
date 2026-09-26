"""Opt-in browser/UDS smoke against a disposable real Git repository."""

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
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="ai-station-projects-") as temporary:
        root = Path(temporary)
        repo = root / "repos/example"
        repo.mkdir(parents=True)
        for args in (
            ["init", "-b", "develop"],
            ["config", "user.name", "Test"],
            ["config", "user.email", "test@example.invalid"],
        ):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        (repo / "README.md").write_text("Original repository\n")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "Initial"], check=True, capture_output=True)
        index = (repo / ".git/index").read_bytes()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        runner_socket = str(root / "runtime/runner.sock")
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT / "host-runner")]),
            "AI_STATION_DATA_DIR": str(root / "data"),
            "AI_STATION_DATA_HOST_PATH": str(root / "data"),
            "AI_STATION_DATABASE_URL": "",
            "AI_STATION_ALLOWED_ROOTS": str(repo.parent),
            "AI_STATION_MODEL_ROOTS": "",
            "AI_STATION_RUNNER_SOCKET": runner_socket,
            "AI_STATION_FRONTEND_DIST": str(ROOT / "frontend/dist"),
        }
        processes = []
        with (root / "server.log").open("w+") as log:

            def launch(args):
                process = subprocess.Popen(
                    [sys.executable, "-m", *args], cwd=ROOT, env=env, stdout=log, stderr=log
                )
                processes.append(process)
                return process

            def start_api():
                process = launch(["uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", str(port)])
                for _ in range(200):
                    try:
                        if httpx.get(url + "/api/health", trust_env=False).status_code == 200:
                            return process
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError("API did not start")

            try:
                runner = launch(["ai_station_runner.main"])
                with httpx.Client(
                    transport=httpx.HTTPTransport(uds=runner_socket), base_url="http://runner"
                ) as host:
                    for _ in range(200):
                        try:
                            if host.get("/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Runner did not start")
                api_process = start_api()
                launch(["app.worker_main"])
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1040})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url + "/#/projects")
                    page.get_by_role("link", name="Register project").click()
                    page.get_by_label("Project name", exact=True).fill("Example workstation project")
                    page.get_by_label("Repository path on host").fill(str(repo))
                    page.get_by_role("button", name="Validate and register").click()
                    page.get_by_text("Clean", exact=True).wait_for()
                    page.get_by_label("Test commands", exact=True).fill('["pytest", "-q"]')
                    page.get_by_label("Agent rules", exact=True).fill("Preserve the existing architecture.")
                    page.get_by_role("button", name="Save project settings").click()
                    page.get_by_text("Project settings saved.", exact=True).wait_for()
                    (repo / "README.md").write_text("Changed by the smoke test\n")
                    page.get_by_role("button", name="Refresh", exact=True).click()
                    page.get_by_text("Uncommitted changes", exact=True).wait_for()
                    page.screenshot(path="/tmp/ai-station-project.png", full_page=True)
                    api_process.terminate()
                    api_process.wait(timeout=10)
                    start_api()
                    page.reload()
                    page.get_by_text("Uncommitted changes", exact=True).wait_for()
                    assert (
                        page.get_by_label("Agent rules").input_value()
                        == "Preserve the existing architecture."
                    )
                    assert page.get_by_label("Test commands").input_value() == '["pytest","-q"]'
                    with httpx.Client(base_url=url, trust_env=False) as client:
                        project = client.get("/api/projects").json()[0]
                        updated = {
                            key: value
                            for key, value in project.items()
                            if key not in {"id", "repo_path", "created_at", "updated_at"}
                        }
                        updated.update(
                            name="Updated in another editor", expected_updated_at=project["updated_at"]
                        )
                        assert client.put(f"/api/projects/{project['id']}", json=updated).status_code == 200
                        assert client.get("/api/runs").json() == []
                    page.get_by_role("button", name="Save project settings").click()
                    page.get_by_text(
                        "Project settings changed. Reload before saving again.", exact=True
                    ).wait_for()
                    page.get_by_role("button", name="Reload saved settings").click()
                    page.get_by_role("heading", name="Updated in another editor", exact=True).wait_for()
                    page.get_by_role("button", name="Prepare isolated worktree").click()
                    page.get_by_text("succeeded", exact=True).wait_for(timeout=20000)
                    page.get_by_text("worktree.json", exact=True).wait_for()
                    page.get_by_role("link", name="Open project and worktrees →").click()
                    page.get_by_text("Prepared and recorded. Preserved for review.", exact=True).wait_for()
                    with httpx.Client(base_url=url, trust_env=False) as client:
                        worktrees = client.get(f"/api/projects/{project['id']}/worktrees").json()
                        assert len(worktrees) == 1 and worktrees[0]["owned"]
                        assert (
                            root / "data" / worktrees[0]["relative_path"] / "README.md"
                        ).read_text() == "Original repository\n"
                    assert (repo / "README.md").read_text() == "Changed by the smoke test\n"
                    page.screenshot(path="/tmp/ai-station-worktree.png", full_page=True)
                    if os.environ.get("AI_STATION_REAL_SANDBOX_TESTS") == "1":
                        page.get_by_label("Test commands").fill('["/usr/bin/python3", "-c", "print(42)"]')
                        page.get_by_role("button", name="Save project settings").click()
                        page.get_by_text("Project settings saved.", exact=True).wait_for()
                        page.get_by_role("button", name="Run saved validation").click()
                        page.get_by_text("1/1 project commands passed.", exact=True).wait_for(timeout=20000)
                        page.get_by_role("heading", name="Project validation", exact=True).wait_for()
                        page.get_by_text("validation.json", exact=True).wait_for()
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                        page.screenshot(path="/tmp/ai-station-validation-mobile.png", full_page=True)
                        page.get_by_role("link", name="Open project and worktrees →").click()
                        page.get_by_role("heading", name="Updated in another editor", exact=True).wait_for()
                        print(
                            "PASS: real sandbox validation, command result UI, JSON artifact and mobile layout"
                        )
                    runner.terminate()
                    runner.wait(timeout=10)
                    page.get_by_role("button", name="Refresh", exact=True).click()
                    page.get_by_text("Host Runner is unavailable", exact=True).wait_for()
                    assert page.get_by_text("Clean", exact=True).count() == 0
                    assert page.get_by_text("Uncommitted changes", exact=True).count() == 0
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path="/tmp/ai-station-project-mobile.png", full_page=True)
                    assert not errors, errors
                    browser.close()
                assert (repo / ".git/index").read_bytes() == index
                print(
                    "PASS: browser registration, real Git over UDS, settings, dirty status, restart persistence, stale edit rejection, worker-driven worktree creation/report, runner outage, mobile layout, and unchanged index"
                )
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


if __name__ == "__main__":
    main()
