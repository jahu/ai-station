"""Opt-in fresh Intel Mac package/backend experiment; never consumer UI proof."""

import http.cookiejar
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODEL = "huihui-qwen3-4b-2507-q4km-macos-x86-64-cpu"
MODEL_SHA = "b1324e2f1bd2e0610d591f54f93e38d90b187f69d1f215f4cace349eade678d7"
PROFILE = "llamacpp-native-darwin-x86_64-b12032-v2"


def require_host():
    required = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "jahu/ai-station",
        "GITHUB_ACTOR": "jahu",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "X64",
        "AI_STATION_REAL_MAC_CONSUMER_TESTS": "1",
    }
    if (
        any(os.environ.get(key) != value for key, value in required.items())
        or platform.system() != "Darwin"
        or platform.machine() != "x86_64"
        or os.geteuid() == 0
    ):
        raise ValueError("Use the explicit fresh standard public Intel Mac experiment")


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, path, body=None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Origin": self.base},
        )
        with self.opener.open(request, timeout=30) as response:
            return json.load(response)

    def wait(self, path, *, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.request(path)
            run = value.get("run", value)
            if run["status"] == "succeeded":
                return value
            if run["status"] in {"failed", "interrupted", "canceled"}:
                raise RuntimeError(
                    "Owned experiment Run ended: " + str(run.get("error_type") or run["status"])
                )
            time.sleep(2)
        raise TimeoutError("The owned experiment Run did not finish within its budget")


def main():
    require_host()
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    state = Path.home() / "Library/Application Support/AI Station"
    if state.exists() or state.is_symlink():
        raise ValueError("The actual package experiment refuses existing AI Station data")
    root = repo / ".tools/mac-consumer-experiment"
    root.parent.mkdir(mode=0o700, exist_ok=True)
    if root.parent.is_symlink():
        raise ValueError("The owned experiment directory cannot cross a symlink")
    root.mkdir(mode=0o700)  # Never adopt partial/unknown experiments.
    proof = {"consumer_gui_qualified": False, "macos_installer_qualified": False, "console_entry": True}
    stage = "build"
    processes = []
    log = (root / "commands.private.log").open("w")

    def save():
        (root / "result.json").write_text(json.dumps(proof, indent=2))

    def command(*argv, timeout=1200):
        return subprocess.run(
            list(map(str, argv)), stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=True
        )

    def progress(value):
        nonlocal stage
        stage = value
        proof["stage"] = stage
        save()
        print(json.dumps({"stage": stage}), flush=True)

    def start(executable):
        import desktop

        process = subprocess.Popen(
            [str(executable), "--console", "--background"], stdout=log, stderr=subprocess.STDOUT
        )
        processes.append(process)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("The actual package exited before readiness")
            url = desktop.ready_url(state)
            if url:
                parsed = urllib.parse.urlsplit(url)
                if parsed.hostname != "127.0.0.1" or parsed.scheme != "http":
                    raise ValueError("The real package readiness was not private loopback")
                return process, url
            time.sleep(1)
        raise TimeoutError("The actual package did not reach readiness")

    def stop(executable, process):
        command(executable, "--stop", timeout=120)
        process.wait(timeout=120)
        if process.returncode:
            raise RuntimeError("The owned package supervisor did not stop cleanly")

    try:
        import desktop_engine

        engine = desktop_engine.select(dict(os.environ))
        os.environ["PATH"] = (
            str(Path(engine.prefix[0]).parent) + os.pathsep + os.environ.get("PATH", os.defpath)
        )
        os.environ["DOCKER_HOST"] = engine.identity[1]
        os.environ.pop("DOCKER_CONTEXT", None)
        py = sys.executable
        (root / "inputs").mkdir(mode=0o700)
        progress("assemble_native_application")
        command(
            py,
            "scripts/macos_desktop_python.py",
            "--architecture",
            "x86_64",
            "--cache",
            root / "inputs",
            "--output",
            root / "python",
            "--download-inputs",
        )
        command(
            py,
            "scripts/macos_application_python.py",
            "--architecture",
            "x86_64",
            "--python-layer",
            root / "python",
            "--output",
            root / "application-python",
        )
        command(
            py,
            "scripts/build_macos_native.py",
            "--architecture",
            "x86_64",
            "--output",
            root / "native-interface",
        )
        progress("build_real_control_plane")
        tag = "ai-station:mac-consumer-" + uuid4().hex[:12]
        command(
            py,
            "scripts/build_control_plane_image.py",
            "--platform",
            "linux/amd64",
            "--builder",
            "desktop-linux",
            "--tag",
            tag,
            "--output",
            root / "image",
        )
        import build_macos_package

        app = root / "AI Station.app"
        metadata = build_macos_package.bundle(
            app,
            root / "application-python",
            root / "native-interface",
            "x86_64",
            tag,
            root / "image/build.json",
            version="0.1.0-qa.1",
        )
        proof["package"] = {
            key: metadata[key] for key in ("bundle_id", "image_id", "source_head", "architecture")
        }
        executable = app / "Contents/MacOS/AI Station"
        command(executable, "--package-check")
        progress("start_actual_package")
        process, url = start(executable)
        parsed = urllib.parse.urlsplit(url)
        client = Client(urllib.parse.urlunsplit(parsed._replace(path="", query="", fragment="")))
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(parsed.fragment).query).get(
            "setup_token", [None]
        )[0]
        progress("first_administrator")
        client.request(
            "/api/auth/setup",
            {
                "username": "QaAdmin",
                "password": "synthetic private desktop acceptance password",
                "local_setup_token": token,
            },
        )
        proof["first_administrator"] = True
        progress("prepare_native_engine")
        observed = client.request("/api/setup/runtimes?profile=" + PROFILE)
        if not observed["installation_available"]:
            raise ValueError("The actual Mac did not admit its native CPU engine")
        runtime = client.request(
            "/api/setup/runtimes",
            {
                "client_request_id": str(uuid4()),
                "profile": PROFILE,
                "manifest_sha256": observed["manifest_sha256"],
                "license_accepted": True,
            },
        )
        client.wait("/api/setup/runtimes/preparations/" + runtime["id"])
        proof["native_engine_prepared"] = True
        progress("download_pinned_native_4b_model")
        catalog = client.request("/api/setup/catalog")
        if catalog["hardware"]["host"]["system"] != "Darwin":
            raise ValueError("The real control plane did not observe the Mac Host Runner")
        entry = next(item for item in catalog["entries"] if item["id"] == MODEL)
        if (
            entry["file"]["sha256"] != MODEL_SHA
            or entry["file"]["size_bytes"] != 2497281312
            or not entry["recommendation"]["fits"]
        ):
            raise ValueError("The pinned public CPU starter changed or does not fit this host")
        download = client.request(
            "/api/setup/downloads",
            {
                "client_request_id": str(uuid4()),
                "catalog_id": MODEL,
                "manifest_sha256": entry["manifest_sha256"],
                "license_accepted": True,
            },
        )
        downloaded = client.wait("/api/setup/downloads/" + download["id"], timeout=1200)
        model = downloaded["model_key"]
        progress("first_real_native_reply")
        conversation = client.request(
            "/api/chat/conversations",
            {
                "title": "Private Mac acceptance",
                "execution_mode": "local",
                "provider": "local-openai-compatible",
                "model": model,
                "max_tokens": 128,
                "temperature": 0,
            },
        )
        turn = client.request(
            "/api/chat/conversations/" + conversation["id"] + "/messages",
            {"content": "What is 2+2? Reply only with the number. /no_think"},
        )
        client.wait("/api/runs/" + turn["id"], timeout=300)
        detail = client.request("/api/chat/conversations/" + conversation["id"])
        if not any(row["role"] == "assistant" and row["content"].strip() for row in detail["messages"]):
            raise ValueError("The actual native model returned no assistant answer")
        proof["first_native_reply"] = True
        progress("stop_restart_and_retained_history")
        stop(executable, process)
        process, next_url = start(executable)
        if urllib.parse.urlsplit(next_url).netloc != parsed.netloc:
            raise ValueError("The preserving restart unexpectedly changed its local address")
        restored = client.request("/api/chat/conversations/" + conversation["id"])
        if restored["messages"] != detail["messages"]:
            raise ValueError("The actual preserving restart changed its conversation")
        proof["restart_retained_history"] = True
        stop(executable, process)
        proof["clean_stop"] = True
        proof["passed"] = True
        progress("backend_experiment_passed_GUI_update_backup_removal_still_required")
    except BaseException as error:
        proof.update(passed=False, error_type=type(error).__name__, stage=stage)
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    command(executable, "--stop", timeout=120)
                    process.wait(timeout=120)
                except BaseException:
                    proof["cleanup_requires_inspection"] = True
        save()
        log.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        print(json.dumps({"experiment_failed": True, "error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
