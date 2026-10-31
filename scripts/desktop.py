"""Local Linux desktop shell for the bundled interpreter and existing supervisor."""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import webbrowser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
READY = "AI_STATION_READY "
READY_FILE = "desktop-ready.json"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def manifest(root):
    value = json.loads((root / "desktop-manifest.json").read_text())
    if (
        value.get("schema") != 1
        or not re.fullmatch(r"[a-f0-9]{64}", value.get("bundle_id", ""))
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", value.get("image_id", ""))
        or value.get("image_tag") != "ai-station:desktop-" + value["bundle_id"][:16]
        or not isinstance(value.get("files"), dict)
        or not 1 <= len(value["files"]) <= 30000
    ):
        raise ValueError("The desktop package manifest is invalid")
    for name, expected in value["files"].items():
        relative = PurePosixPath(name)
        path = root / name
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != name
            or "\\" in name
            or not path.resolve().is_relative_to(root.resolve())
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
        ):
            raise ValueError("The desktop package contains an invalid file reference")
    return value


def verify(root, value):
    for name, expected in value["files"].items():
        path = root / name
        if not path.is_file() or digest(path) != expected:
            raise ValueError("A desktop package file is missing or changed: " + name)


def state_root():
    parent = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser().resolve()
    root = parent / "ai-station-desktop"
    if root.is_symlink():
        raise ValueError("Desktop data must not be a symlink")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("Desktop data must be owned by you and not writable by others")
    return root


def owned_folder(root, name):
    folder = root / name
    if folder.is_symlink():
        raise ValueError("Desktop storage must not cross a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def install_copy(root, source, value):
    if root.resolve().is_relative_to(source.resolve()):
        raise ValueError("Desktop data must be outside the application package")
    releases = owned_folder(root, "releases")
    target = releases / value["bundle_id"]
    if target.is_symlink():
        raise ValueError("Installed desktop code must not be a symlink")
    if target.exists():
        if manifest(target) != value:
            raise ValueError("The installed version differs from this package")
        return target
    verify(source, value)
    temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=releases))
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True, symlinks=True)
        verify(temporary, value)
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def free_port():
    for port in range(8765, 8865):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No local AI Station port is free; no other application was stopped")


def configuration(root):
    config = root / "desktop.env"
    if config.is_symlink():
        raise ValueError("Desktop configuration must not be a symlink")
    if config.exists():
        info = config.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o022
        ):
            raise ValueError("Desktop configuration must remain an owned regular file")
        return config
    data = owned_folder(root, "data")
    if (data / "db").is_symlink() or (data / "db/ai-station.sqlite").exists():
        raise ValueError(
            "Existing station data needs its original configuration. It was not adopted or changed."
        )
    project = "ai-station-desktop-" + hashlib.sha256(str(root).encode()).hexdigest()[:12]
    values = {
        "AI_STATION_DATA_HOST_PATH": str(data),
        "AI_STATION_ACCESS_PROFILE": "accounts",
        "AI_STATION_PORT": str(free_port()),
        "COMPOSE_PROJECT_NAME": project,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(key + "=" + json.dumps(value, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, config)  # Atomic publication without replacing user configuration.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return config


def prerequisites():
    if platform.system() != "Linux" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("This desktop package is for Linux x86-64")
    if not shutil.which("docker"):
        raise RuntimeError("Install and start Docker first, then open AI Station again")
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = os.environ.get("DOCKER_HOST") if not context else None
    if not endpoint:
        result = subprocess.run(
            [
                "docker",
                "context",
                "inspect",
                *([context] if context else []),
                "--format",
                '{{(index .Endpoints "docker").Host}}',
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        endpoint = result.stdout.strip() if result.returncode == 0 else ""
    if not endpoint.startswith("unix:///"):
        raise RuntimeError("Select a local Docker engine for this workstation; remote Docker is not used")
    for command in (["docker", "compose", "version"], ["docker", "info"]):
        result = subprocess.run(command, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError(
                "Docker and Compose must be running and accessible to your user. "
                "AI Station did not change permissions or Docker settings."
            )


def import_image(root, value, log):
    result = subprocess.run(
        ["docker", "image", "inspect", value["image_tag"], "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 0:
        if result.stdout.strip() != value["image_id"]:
            raise ValueError("The desktop image tag has a different identity; it was not overwritten")
        return
    archive = root / "control-plane.tar"
    if digest(archive) != value["files"]["control-plane.tar"]:
        raise ValueError("The packaged application image changed")
    with tarfile.open(archive) as source:
        info = source.getmember("manifest.json")
        if not info.isfile() or info.size > 1024 * 1024:
            raise ValueError("The packaged Docker manifest is invalid")
        manifests = json.load(source.extractfile(info))
        if (
            not isinstance(manifests, list)
            or len(manifests) != 1
            or manifests[0].get("RepoTags") != [value["image_tag"]]
        ):
            raise ValueError("The archive contains an unexpected application image")
    subprocess.run(["docker", "load", "--input", str(archive)], stdout=log, stderr=log, check=True)
    observed = subprocess.check_output(
        ["docker", "image", "inspect", value["image_tag"], "--format", "{{.Id}}"], text=True
    ).strip()
    if observed != value["image_id"]:
        raise ValueError("The imported application image could not be verified")


def launch_environment():
    # The desktop bundle has its own configuration. Shell variables from a
    # developer's other station must not redirect its data, credentials or port.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AI_STATION_", "COMPOSE_", "PYTHON"))
    }


def browser_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
    ):
        raise ValueError("The desktop supervisor returned an unexpected local address")
    fragment = parsed.fragment
    if fragment:
        if not re.fullmatch(r"/(?:setup/models)?\?setup_token=[A-Za-z0-9_-]{43}", fragment):
            raise ValueError("The desktop supervisor returned an invalid setup link")
        fragment = fragment.replace("/?", "/setup/models?", 1)
    return urlunsplit(parsed._replace(fragment=fragment))


def publish_ready(root, url):
    """Private handoff to later desktop clicks; never an ordinary log entry."""
    url = browser_url(url)
    descriptor, temporary = tempfile.mkstemp(prefix=".desktop-ready-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump({"url": url}, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, root / READY_FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)


def reopen(root):
    """Called only after the owning desktop process's lock is observed held."""
    try:
        descriptor = os.open(root / READY_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > 4096
        ):
            raise ValueError("The desktop readiness link must remain a private owned file")
        value = json.load(source)
    if not isinstance(value, dict) or set(value) != {"url"} or not isinstance(value["url"], str):
        raise ValueError("The desktop readiness link is invalid")
    webbrowser.open(browser_url(value["url"]))
    return True


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "AI Station is still stopping. Inspect its desktop log before restarting."
            ) from None


def supervise(
    root, config, value, log, *, console=False, on_ready=lambda: None, on_ready_url=lambda url: None
):
    env = {**launch_environment(), "AI_STATION_APP_IMAGE": value["image_tag"], "PYTHONNOUSERSITE": "1"}
    proc = subprocess.Popen(
        [
            str(root / "python/bin/python3"),
            "-I",
            str(root / "scripts/launch.py"),
            "--config",
            str(config),
            "--desktop",
            "--no-build",
        ],
        env=env,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    ready = queue.Queue()

    def read():
        for line in proc.stdout:
            if line.startswith(READY):
                try:
                    ready.put(browser_url(json.loads(line[len(READY) :])["url"]))
                except (ValueError, TypeError, KeyError):
                    ready.put(None)
            else:
                log.write(line)
                log.flush()
        ready.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        try:
            url = ready.get(timeout=180)
        except queue.Empty:
            raise RuntimeError("AI Station did not become ready; inspect the private desktop log") from None
        if not url or proc.poll() is not None:
            raise RuntimeError("AI Station could not start; see the private desktop log")
        on_ready_url(url)
        on_ready()
        if console:
            print(READY + json.dumps({"url": url}), flush=True)
            proc.wait()
        else:
            webbrowser.open(url)
            while proc.poll() is None:
                answer = dialog(
                    "--question",
                    "--text=AI Station is running locally.\n\nYou can close your browser and keep working agents running. Keep this window open or minimized.\n\nStop AI Station to shut down this desktop installation; your data stays saved.",
                    "--ok-label=Open AI Station",
                    "--cancel-label=Stop AI Station",
                )
                if answer != 0:
                    break
                webbrowser.open(url)
    finally:
        stop(proc)
        reader.join(timeout=5)


def dialog(*args):
    return subprocess.run(["zenity", "--title=AI Station", "--width=540", *args], check=False).returncode


class Preparation:
    """An indeterminate stage display, never a fabricated transfer percentage."""

    def __init__(self, console):
        self.proc = None
        if not console:
            self.proc = subprocess.Popen(
                ["zenity", "--progress", "--pulsate", "--no-cancel", "--title=AI Station", "--width=540"],
                stdin=subprocess.PIPE,
                text=True,
            )

    def stage(self, text):
        if self.proc is None:
            print(text, flush=True)
        elif self.proc.poll() is None:
            try:
                self.proc.stdin.write("# " + text + "\n")
                self.proc.stdin.flush()
            except BrokenPipeError:
                pass  # Closing this display does not interrupt image import.

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--console", action="store_true", help="Explicit terminal supervision instead of desktop dialogs"
    )
    args = parser.parse_args()
    os.umask(0o077)

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    if not args.console and not shutil.which("zenity"):
        raise RuntimeError("The Linux desktop package requires Zenity; console mode is also available")
    value = manifest(ROOT)
    root = state_root()
    lock = os.open(root / "desktop.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not reopen(root):
                message = (
                    "AI Station is still starting. Its existing progress window will open the app when ready."
                )
                if args.console:
                    print(message, flush=True)
                else:
                    dialog("--info", "--text=" + message)
            return
        acquired = True
        # A new owner must never reuse the previous process's readiness link.
        (root / READY_FILE).unlink(missing_ok=True)
        prerequisites()
        if not args.console and not (root / "desktop.env").exists():
            answer = dialog(
                "--question",
                "--text=Set up your local AI Station?\n\nThe application and data stay in your private user folder. This prepares the bundled app; models are chosen afterward. Docker may download the private web-search service. No drivers or existing models are changed.",
                "--ok-label=Set up AI Station",
                "--cancel-label=Cancel",
            )
            if answer != 0:
                return
        progress = Preparation(args.console)
        try:
            progress.stage("Checking and preparing your private application folder…")
            installed = install_copy(root, ROOT, value)
            config = configuration(root)
            if installed.resolve() != ROOT.resolve():
                progress.close()
                executable = str(installed / "python/bin/python3")
                os.execve(
                    executable,
                    [executable, "-I", str(installed / "scripts/desktop.py"), *sys.argv[1:]],
                    launch_environment(),
                )
            with (root / "desktop.log").open("a", encoding="utf-8") as log:
                progress.stage("Preparing the bundled application image…")
                import_image(installed, value, log)
                progress.stage("Starting your local AI Station…")
                supervise(
                    installed,
                    config,
                    value,
                    log,
                    console=args.console,
                    on_ready=progress.close,
                    on_ready_url=lambda url: publish_ready(root, url),
                )
        finally:
            progress.close()
    finally:
        try:
            if acquired:
                (root / READY_FILE).unlink(missing_ok=True)
        finally:
            os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, queue.Empty) as error:
        if "--console" not in sys.argv and shutil.which("zenity"):
            dialog("--error", "--text=" + str(error))
        else:
            raise SystemExit(str(error))
