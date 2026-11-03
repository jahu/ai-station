"""Opt-in fresh Intel Mac package/backend experiment; never consumer UI proof."""

import hashlib
import http.cookiejar
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODEL = "huihui-qwen3-4b-2507-q4km-macos-x86-64-cpu"
MODEL_SHA = "b1324e2f1bd2e0610d591f54f93e38d90b187f69d1f215f4cace349eade678d7"
PROFILE = "llamacpp-native-darwin-x86_64-b12032-v2"
# The real startup includes independent 180-second bridge and readiness budgets
# plus package retention and database preparation. A 300-second whole-operation
# limit can cancel these legitimate steps before their own bounds are reached.
STARTUP_TIMEOUT = 900


def startup_stage(path, *, after=0):
    from desktop import STARTUP_STAGES

    latest = None
    if path.is_file():
        with path.open(errors="replace") as stream:
            stream.seek(after)
            for line in stream:
                if not line.startswith('{"desktop_startup_stage": '):
                    continue
                try:
                    value = json.loads(line).get("desktop_startup_stage")
                except ValueError:
                    continue
                if value in STARTUP_STAGES.values():
                    latest = value
    return latest


def sdk_cache_state(state):
    """Inspect only the pinned public SDK object's metadata/hash, never its bytes."""
    from ai_station_runner.darwin_llama_environment import Environment

    item = Environment(PROFILE).recipe()["inputs"][0]
    path = state / "data/models/store" / item["sha256"]
    try:
        if path.parent.resolve() != path.parent:
            raise ValueError("The SDK cache parent changed")
        info = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    result = {
        "exists": True,
        "diagnostic_only": True,
        "symlink": stat.S_ISLNK(info.st_mode),
        "size_bytes": info.st_size,
        "expected_bytes": item["size_bytes"],
        "uid": info.st_uid,
        "native_uid": os.geteuid(),
        "link_count": info.st_nlink,
        "mode": oct(stat.S_IMODE(info.st_mode)),
    }
    if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_size == item["size_bytes"]:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            result["sha256_matches"] = hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"]
    return result


def startup_errors(state, *, log_name="desktop.log"):
    """Read bounded structured faults, never raw private supervisor log text."""
    from launch import DESKTOP_SERVICE_STAGES

    if log_name not in {"desktop.log", "commands.private.log"}:
        raise ValueError("Choose only this experiment's fixed startup log")
    result = {"stage": None, "errors": []}
    try:
        descriptor = os.open(state / log_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return result
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("The owned startup log is not a private regular file")
        stream.seek(max(0, info.st_size - 65536))
        tail = stream.read(65536).decode(errors="replace")
    observed = []
    for line in tail.splitlines():
        if line.startswith('{"desktop_service_stage": '):
            try:
                stage = json.loads(line).get("desktop_service_stage")
            except ValueError:
                continue
            if isinstance(stage, str) and stage in DESKTOP_SERVICE_STAGES:
                result["stage"] = stage
        if not line.startswith('{"desktop_startup_error": '):
            continue
        try:
            value = json.loads(line)["desktop_startup_error"]
        except (ValueError, KeyError):
            continue
        if not isinstance(value, dict) or value.get("error_type") not in {
            "RuntimeError",
            "ValueError",
            "OSError",
            "PermissionError",
            "FileNotFoundError",
            "CalledProcessError",
            "TimeoutExpired",
            "HTTPError",
            "HTTPStatusError",
            "ConnectError",
            "ReadTimeout",
            "ConnectTimeout",
        }:
            continue
        item = {"error_type": value["error_type"], "frames": []}
        frames = value.get("frames")
        for frame in frames[-12:] if isinstance(frames, list) else []:
            if (
                isinstance(frame, dict)
                and isinstance(frame.get("file"), str)
                and re.fullmatch(r"[A-Za-z0-9_.-]+\.py", frame["file"])
                and type(frame.get("line")) is int
                and 0 < frame["line"] < 2**31
                and isinstance(frame.get("function"), str)
                and re.fullmatch(r"[A-Za-z0-9_<>]{1,128}", frame["function"])
            ):
                item["frames"].append({key: frame[key] for key in ("file", "line", "function")})
        for key in ("errno", "return_code"):
            if type(value.get(key)) is int and -(2**31) < value[key] < 2**31:
                item[key] = value[key]
        observed.append(item)
    result["errors"] = observed[-8:]
    return result


def service_states(engine, state):
    """Read only fixed service state codes in this fresh QA station's project."""
    from dotenv import dotenv_values

    project = dotenv_values(state / "desktop.env", interpolate=False).get("COMPOSE_PROJECT_NAME")
    if not isinstance(project, str) or not re.fullmatch(r"ai-station-desktop-[a-f0-9]{12}", project):
        return {"unavailable": "NoOwnedProject"}

    def query(*args):
        result = subprocess.run(
            engine.command(*args), env=engine.environment, capture_output=True, text=True, timeout=5
        )
        if result.returncode:
            raise RuntimeError("Owned service inspection failed")
        return result.stdout

    observed = []
    rows = query(
        "container",
        "ls",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.project=" + project,
        "--format",
        '{{.ID}} {{.Label "com.docker.compose.service"}}',
    )
    for row in rows.splitlines()[:8]:
        parts = row.split()
        if (
            len(parts) != 2
            or not re.fullmatch(r"[a-f0-9]{64}", parts[0])
            or parts[1] not in {"ai-station", "worker", "scheduler", "search", "runner-connection"}
        ):
            continue
        value = json.loads(query("container", "inspect", parts[0], "--format", "{{json .State}}"))
        if not isinstance(value, dict):
            raise ValueError("Unexpected owned service state")
        item = {"service": parts[1]}
        if value.get("Status") in {
            "created",
            "running",
            "restarting",
            "removing",
            "paused",
            "exited",
            "dead",
        }:
            item["status"] = value["Status"]
        if type(value.get("ExitCode")) is int:
            item["exit_code"] = value["ExitCode"]
        if type(value.get("OOMKilled")) is bool:
            item["oom_killed"] = value["OOMKilled"]
        health = value.get("Health")
        health = health.get("Status") if isinstance(health, dict) else None
        if health in {"healthy", "unhealthy", "starting"}:
            item["health"] = health
        observed.append(item)
    return observed


def native_process_states(roots):
    """Only owned ancestry and fixed process names; never arguments/environment."""
    if not roots or any(type(pid) is not int or pid <= 0 for pid in roots):
        raise ValueError("Use live owned QA process identities")
    result = subprocess.run(
        ["/bin/ps", "-A", "-o", "pid=,ppid=,stat=,pcpu=,etime=,comm="],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    rows = {}
    known = {
        "AI Station",
        "ai-station-native",
        "docker",
        "com.docker.cli",
        "docker-compose",
        "docker-credential-desktop",
        "docker-credential-osxkeychain",
        "xcodebuild",
        "xctest",
    }
    for line in result.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6:
            continue
        pid, parent, status, cpu, elapsed, command = parts
        try:
            pid, parent, cpu = int(pid), int(parent), float(cpu)
        except ValueError:
            continue
        if (
            pid <= 0
            or not 0 <= cpu <= 100000
            or not re.fullmatch(r"[A-Za-z+<>0-9-]{1,12}", status)
            or not re.fullmatch(r"[0-9:-]{1,24}", elapsed)
        ):
            continue
        name = Path(command).name
        kind = "python" if re.fullmatch(r"python(?:[0-9.]+)?", name) else name if name in known else "other"
        rows[pid] = {
            "pid": pid,
            "parent_pid": parent,
            "kind": kind,
            "state": status,
            "cpu_percent": cpu,
            "elapsed": elapsed,
        }
    owned = set(roots)
    while True:
        added = {pid for pid, row in rows.items() if row["parent_pid"] in owned} - owned
        if not added:
            break
        owned.update(added)
    return [rows[pid] for pid in sorted(owned) if pid in rows][:32]


def execution_environment():
    # CI publication authority stays in this trusted QA parent. Neither build
    # subprocesses nor the installed application/model receive those tokens.
    return {
        key: value for key, value in os.environ.items() if not key.startswith(("GH_", "GITHUB_", "ACTIONS_"))
    }


def producer():
    # Developer build inputs belong to this reviewed checkout. The installed
    # app still runs its own bundled interpreter with -IB and no source paths.
    # Import before expensive work so missing build inputs fail immediately.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host-runner"))
    import build_macos_package

    return build_macos_package


def failure(error):
    detail = {"error_type": type(error).__name__}
    frames = traceback.extract_tb(error.__traceback__)
    if frames:
        frame = frames[-1]
        detail["failure_site"] = {
            "file": Path(frame.filename).name,
            "line": frame.lineno,
            "function": frame.name,
        }
    if isinstance(error, ModuleNotFoundError):
        detail["missing_module"] = error.name
    if isinstance(error, RunFailed):
        detail["owned_run_failure"] = error.evidence
    return detail  # Never include exception messages, locals or source lines.


class RunFailed(RuntimeError):
    """Publish only coordinates/codes from an owned Run, never arbitrary log text."""

    def __init__(self, run, events):
        super().__init__("The owned experiment Run did not succeed")
        self.evidence = {"id": str(UUID(run["id"])), "status": run["status"]}
        code = run.get("error_type")
        if isinstance(code, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", code):
            self.evidence["error_type"] = code
        stderr = "".join(
            event.get("payload", {}).get("text", "")
            for event in events
            if event.get("event_type") == "stderr"
        )[-65536:]
        frames = []
        for filename, line, function in re.findall(
            r'File "([^"\n]+)", line ([0-9]+), in ([A-Za-z0-9_<>]+)', stderr
        )[-12:]:
            name = Path(filename).name
            if re.fullmatch(r"[A-Za-z0-9_.-]+\.py", name):
                frames.append({"file": name, "line": int(line), "function": function})
        self.evidence["native_frames"] = frames
        classes = re.findall(r"^([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception)):", stderr, re.MULTILINE)
        if classes:
            self.evidence["native_error_type"] = classes[-1]
        # Numeric transport/OS failures help diagnose downloads without copying
        # a URL, request header, setup link, account field or exception message.
        text = stderr + "\n" + str(run.get("error_message") or "")
        self.evidence["errno"] = sorted({int(v) for v in re.findall(r"\[Errno ([0-9]+)\]", text)})
        self.evidence["http_status"] = sorted(
            {int(v) for v in re.findall(r"(?:HTTP Error |status code |error ')([45][0-9]{2})\b", text)}
        )


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
        observed_status = None
        while time.monotonic() < deadline:
            value = self.request(path)
            run = value.get("run", value)
            if run["status"] != observed_status:
                observed_status = run["status"]
                print(json.dumps({"observed_run_status": observed_status}), flush=True)
            if run["status"] == "succeeded":
                return value
            if run["status"] in {"failed", "interrupted", "canceled"}:
                # Preserve the actual native fault before the disposable host
                # is cleaned up. Evidence deliberately excludes message text.
                try:
                    events = self.request("/api/runs/" + str(UUID(run["id"])) + "/events")
                except (OSError, ValueError):
                    events = []
                raise RunFailed(run, events)
            time.sleep(2)
        raise TimeoutError("The owned experiment Run did not finish within its budget")

    def created_in_browser(self, path, *, timeout=30):
        """Observe one fresh UI-created record; never substitute an API write."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self.request(path)
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError("The fresh browser action has ambiguous records")
            if rows:
                UUID(rows[0]["id"])
                return rows[0]
            time.sleep(1)
        raise TimeoutError("The browser did not create its ordinary record")


def main():
    require_host()
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    ownership = repo / ".native-mac/desktop-installed"
    if (
        ownership.is_symlink()
        or not ownership.is_file()
        or ownership.stat().st_size > 1024
        or ownership.stat().st_uid != os.geteuid()
        or stat.S_IMODE(ownership.stat().st_mode) & 0o077
    ):
        raise ValueError("This experiment requires its fresh private Desktop installation receipt")
    installed = json.loads(ownership.read_text())
    if (
        installed.get("run_id") != os.environ.get("GITHUB_RUN_ID")
        or installed.get("uid") != os.geteuid()
        or installed.get("installer_sha256")
        != "98da1a82dac734ba6a14c3e0379f5655ce0bd52a04cf8bb47f4e4642c914f695"
    ):
        raise ValueError("The Desktop installation belongs to another QA operation")
    package_builder = producer()
    state = Path.home() / "Library/Application Support/AI Station"
    if state.exists() or state.is_symlink():
        raise ValueError("The actual package experiment refuses existing AI Station data")
    root = repo / ".tools/mac-consumer-experiment"
    root.parent.mkdir(mode=0o700, exist_ok=True)
    if root.parent.is_symlink():
        raise ValueError("The owned experiment directory cannot cross a symlink")
    root.mkdir(mode=0o700)  # Never adopt partial/unknown experiments.
    from macos_qa_status import Status

    status = Status(package_builder.git("rev-parse", "HEAD"))
    # Only the status publisher retains this job's short-lived authority. Drop
    # inherited CI tokens before any producer, Docker or application subprocess.
    for key in list(os.environ):
        if key.startswith(("GH_", "ACTIONS_")) or key == "GITHUB_TOKEN":
            os.environ.pop(key)
    gui = os.environ.get("AI_STATION_REAL_MAC_CONSUMER_GUI_TESTS") == "1"
    proof = {"consumer_gui_qualified": False, "macos_installer_qualified": False, "console_entry": not gui}
    stage = "build"
    startup_offset = 0
    processes = []
    ui_processes = []
    engine = None
    log = (root / "commands.private.log").open("w")

    def save():
        (root / "result.json").write_text(json.dumps(proof, indent=2))

    def command(*argv, timeout=1200):
        return subprocess.run(
            list(map(str, argv)),
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=True,
            env=execution_environment(),
        )

    def progress(value):
        nonlocal stage
        stage = value
        proof["stage"] = stage
        save()
        print(json.dumps({"stage": stage}), flush=True)
        # Fixed stage names only: expose live progress through check annotations
        # without publishing private commands, setup URLs or account material.
        print(f"::notice title=Mac package QA::{stage}", flush=True)
        from ai_station_runner.darwin_telemetry import memory

        facts = memory()
        status.post(
            "pending",
            f"{stage}; RAM available={facts.get('available_mib')}MiB; "
            f"swap={facts.get('swap_used_mib')}MiB; disk={shutil.disk_usage(root).free // 1024**2}MiB",
        )

    def launch_ui(selection, receipt):
        controller = subprocess.Popen(
            [
                "/usr/bin/xcodebuild",
                "test",
                "-project",
                str(repo / "packaging/macos/acceptance/NativeAcceptance.xcodeproj"),
                "-scheme",
                "NativeAcceptance",
                "-configuration",
                "Debug",
                "-only-testing:NativeAcceptanceTests/" + selection,
                "-destination",
                "platform=macOS",
                "-parallel-testing-enabled",
                "NO",
                "-derivedDataPath",
                str(root / "gui-build"),
                "-resultBundlePath",
                str(root / (receipt + ".xcresult")),
                "CODE_SIGN_IDENTITY=-",
            ],
            env=execution_environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        ui_processes.append(controller)
        return controller

    def guided_action(method):
        controller = launch_ui("NativeGuidedAcceptanceTests/" + method, method)
        controller.wait(timeout=480)
        if controller.returncode:
            raise RuntimeError("The actual guided browser action failed")

    def start(executable, *, first_gui=False):
        nonlocal startup_offset
        import desktop

        log.flush()
        startup_offset = os.fstat(log.fileno()).st_size
        process = subprocess.Popen(
            [str(executable), *([] if gui else ["--console", "--background"])],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=execution_environment(),
        )
        processes.append(process)
        if first_gui:
            (root / "gui-process.json").write_text(json.dumps({"pid": process.pid}))
            controller = launch_ui("NativeConsumerAcceptanceTests", "gui-result")
        deadline = time.monotonic() + (1200 if first_gui else STARTUP_TIMEOUT)
        observed_stage = None
        next_process_sample = 0
        while time.monotonic() < deadline:
            if first_gui and startup_errors(root, log_name="commands.private.log")["errors"]:
                raise RuntimeError("The actual package reported a structured native startup fault")
            current = startup_stage(root / "commands.private.log", after=startup_offset)
            if current and current != observed_stage:
                observed_stage = current
                proof["native_startup_stage"] = current
                progress("startup_" + current)
            if first_gui and current == "application_services" and time.monotonic() >= next_process_sample:
                roots = [child.pid for child in [process, *ui_processes] if child.poll() is None]
                try:
                    observations = proof.setdefault("native_startup_processes", [])
                    observations.append(native_process_states(roots))
                    del observations[:-12]
                    save()
                except (OSError, ValueError, subprocess.SubprocessError) as sample_error:
                    proof["process_observation_unavailable"] = type(sample_error).__name__
                next_process_sample = time.monotonic() + 30
            if first_gui and controller.poll() not in {None, 0}:
                raise RuntimeError("The actual native/browser acceptance failed")
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
            # The fixed DOCKER_HOST selects the engine. Its context-named
            # builder refuses that explicit endpoint; use the daemon's default.
            "default",
            "--tag",
            tag,
            "--output",
            root / "image",
        )
        progress("assemble_actual_application_bundle")
        app = root / "AI Station.app"
        metadata = package_builder.bundle(
            app,
            root / "application-python",
            root / "native-interface",
            "x86_64",
            tag,
            root / "image/build.json",
        )
        proof["package"] = {
            key: metadata[key] for key in ("bundle_id", "image_id", "source_head", "architecture")
        }
        executable = app / "Contents/MacOS/AI Station"
        command(executable, "--package-check")
        # A consumer imports a prebuilt image; the developer's preceding image
        # build can leave guest cache occupying host RAM. Restart only this QA
        # job's newly installed Desktop, retaining its image store and settings.
        progress("cold_start_owned_desktop_after_build")
        command(engine.identity[0], "desktop", "stop", "--timeout", "60", timeout=90)
        command(engine.identity[0], "desktop", "start", "--timeout", "240", timeout=270)
        from macos_desktop_qa_ready import wait_for_engine

        wait_for_engine()
        if desktop_engine.select(dict(os.environ)).identity != engine.identity:
            raise ValueError("The owned Desktop restart changed its pinned local endpoint")
        progress("start_actual_package")
        process, url = start(executable, first_gui=gui)
        parsed = urllib.parse.urlsplit(url)
        client = Client(urllib.parse.urlunsplit(parsed._replace(path="", query="", fragment="")))
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(parsed.fragment).query).get(
            "setup_token", [None]
        )[0]
        progress("first_administrator")
        if gui:
            controller = ui_processes[-1]
            controller.wait(timeout=600)
            if controller.returncode:
                raise RuntimeError("The actual browser did not complete administrator setup")
            client.request(
                "/api/auth/login",
                {
                    "username": "QaAdmin",
                    "password": "synthetic private desktop acceptance password",
                },
            )
            proof["native_browser_first_administrator"] = True
        else:
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
        if gui:
            guided_action("testPrepareNativeEngine")
            runtime = client.created_in_browser("/api/setup/runtimes/preparations?profile=" + PROFILE)
            if (
                runtime["recipe"]["profile"] != PROFILE
                or runtime["manifest_sha256"] != observed["manifest_sha256"]
            ):
                raise ValueError("The browser prepared another native engine")
        else:
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
        if gui:
            guided_action("testDownloadSelectedStarter")
            download = client.created_in_browser("/api/setup/downloads")
            if download["entry"]["id"] != MODEL or download["manifest_sha256"] != entry["manifest_sha256"]:
                raise ValueError("The browser selected another model")
        else:
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
        if gui:
            guided_action("testFirstModelAnswer")
            conversation = client.created_in_browser("/api/chat/conversations")
            if conversation["model"] != model or conversation["execution_mode"] != "assistant":
                raise ValueError("The browser opened a different model or conversation")
            detail = client.request("/api/chat/conversations/" + conversation["id"])
            replies = [
                row for row in detail["messages"] if row["role"] == "assistant" and row["content"].strip()
            ]
            if len(replies) != 1:
                raise ValueError("The browser did not receive one real first answer")
            client.wait("/api/runs/" + str(UUID(replies[0]["run_id"])), timeout=300)
            proof["native_browser_engine_model_and_first_reply"] = True
        else:
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
        progress("real_native_followup_after_restart")
        followup = client.request(
            "/api/chat/conversations/" + conversation["id"] + "/messages",
            {"content": "What is 3+3? Reply only with the number. /no_think"},
        )
        client.wait("/api/runs/" + followup["id"], timeout=300)
        continued = client.request("/api/chat/conversations/" + conversation["id"])
        if not any(
            row["role"] == "assistant" and row["run_id"] == followup["id"] and row["content"].strip()
            for row in continued["messages"]
        ):
            raise ValueError("The restarted installation could not continue its conversation")
        proof["native_reply_after_restart"] = True
        stop(executable, process)
        proof["clean_stop"] = True
        proof["passed"] = True
        progress("backend_experiment_passed_GUI_update_backup_removal_still_required")
        status.post("success", "Backend scenario passed; full GUI/installer still unqualified")
    except BaseException as error:
        proof.update(passed=False, stage=stage, **failure(error))
        proof["native_startup_stage"] = startup_stage(root / "commands.private.log", after=startup_offset)
        proof["startup_files_present"] = [
            name for name in ("desktop.env", "desktop.log", "desktop-ready.json") if (state / name).is_file()
        ]
        save()  # Preserve the fault before bounded process cleanup can block.
        print(json.dumps({"experiment_failed_at": stage, **failure(error)}), flush=True)
        try:
            proof["supervisor_startup_errors"] = startup_errors(state)
        except (OSError, ValueError):
            proof["startup_log_inspection_unavailable"] = True
        try:
            if engine is not None:
                proof["owned_service_states"] = service_states(engine, state)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as inspection_error:
            proof["service_inspection_unavailable"] = type(inspection_error).__name__
        if stage == "prepare_native_engine":
            try:
                proof["native_sdk_cache"] = sdk_cache_state(state)
            except (OSError, ValueError):
                proof["sdk_cache_inspection_unavailable"] = True
        save()
        try:
            status.post("failure", f"{stage}: {type(error).__name__}")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            proof["status_publish_failed"] = True
        raise
    finally:
        for controller in ui_processes:
            if controller.poll() is None:
                controller.terminate()  # This immediate, unreaped Xcode child only.
                try:
                    controller.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    controller.kill()
                    controller.wait(timeout=5)
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
        print(json.dumps({"experiment_failed": True, **failure(error)}), flush=True)
        raise SystemExit(1) from None
